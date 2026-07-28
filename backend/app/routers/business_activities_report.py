"""
app/routers/business_activities_report.py
REPORTS-DEPT-1 Phase 6 — the cross-department Business Activities PDF.

Distinct from the two existing, narrower reports:
  - internal_issues.py's download_internal_ops_report  (Issues only)
  - activity_logs.py's download route                  (Activity Log only)

This one pulls together activity logs, issues, configurable team metrics,
and Sales Record data (Sales department's teams only — Commissions is
deliberately excluded, client-confirmed) into ONE document, segmented by
department -> team. Built for a business owner/partner/investor to get a
same-day cross-department pulse, not a deep audit trail.

Grouping rule: team metrics are configured PER TEAM (Sales and Digital
Marketing almost certainly track different things), so aggregation
happens at the team level, never blended across teams within a
department. A team with zero activity logs AND zero issues for the
period is silently dropped; a department where every team under it is
empty is silently dropped too. Sales Record figures only ever appear
under whichever team(s) actually have direct_sales rows attributed to
them via source_team (background attribution — REPORTS-DEPT-1 Phase 4c).

Full activity text is included per client decision ("mostly this pdf
will be for daily report" — reasonable volume at daily granularity).

Owner/ops_manager only. Rate limited via its own Redis key, separate
from the other two reports' limits.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from typing import Optional
from datetime import datetime, timezone
import logging
import os

from app.database import get_supabase
from app.dependencies import get_current_org

router = APIRouter()
logger = logging.getLogger(__name__)

TEAL  = "#0D9488"
RED   = "#dc2626"
AMBER = "#d97706"
GREEN = "#16a34a"


def _is_manager(org: dict) -> bool:
    template = (org.get("roles") or {}).get("template", "").lower()
    return template in ("owner", "ops_manager")


def _check_rate_limit(org_id: str) -> bool:
    """Same 10/hr pattern as the other two reports, own Redis key so the
    limits don't share a bucket. Fail open (S14) if Redis is unavailable."""
    try:
        import redis as _redis
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return True
        r = _redis.from_url(url, decode_responses=True, socket_connect_timeout=1)
        key = f"business_activities_report_limit:{org_id}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, 3600)
        return count <= 10
    except Exception as exc:
        logger.warning("_check_rate_limit (business activities report): Redis unavailable — allowing: %s", exc)
        return True


@router.get("/business-activities/report/download")
def download_business_activities_report(
    date_from: Optional[str] = None,
    date_to:   Optional[str] = None,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    if not _is_manager(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Manager access required"},
        )

    org_id = org["org_id"]

    if not _check_rate_limit(org_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "message": "You can download up to 10 reports per hour."},
        )

    now = datetime.now(timezone.utc)
    # Defaults to today — "mostly this pdf will be for daily report"
    if not date_from:
        date_from = now.date().isoformat()
    if not date_to:
        date_to = now.date().isoformat()

    # ── Org config: departments, teams, team metrics ────────────────────────
    org_row = (
        db.table("organisations")
        .select("name, departments, teams, team_metrics")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    org_data = org_row.data
    if isinstance(org_data, list):
        org_data = org_data[0] if org_data else {}
    org_data = org_data or {}
    org_name = org_data.get("name") or "Organisation"
    departments = [d for d in (org_data.get("departments") or []) if d.get("is_active", True)]
    departments.sort(key=lambda d: d.get("sort_order", 0))
    teams = [t for t in (org_data.get("teams") or []) if t.get("is_active", True)]
    team_metrics_config = org_data.get("team_metrics") or []

    dept_by_id = {d["id"]: d for d in departments}
    teams_by_dept: dict = {}
    unassigned_teams = []
    for t in teams:
        dept_id = t.get("department_id")
        if dept_id and dept_id in dept_by_id:
            teams_by_dept.setdefault(dept_id, []).append(t)
        else:
            unassigned_teams.append(t)

    # ── Data for the period ──────────────────────────────────────────────────
    logs_result = (
        db.table("activity_logs")
        .select("*, user:user_id(id, full_name, team)")
        .eq("org_id", org_id)
        .gte("log_date", date_from)
        .lte("log_date", date_to)
        .order("log_date", desc=False)
        .execute()
    )
    logs = logs_result.data or []
    if isinstance(logs, dict):
        logs = [logs]

    issues_result = (
        db.table("internal_issues")
        .select("*, reporter:reported_by(id, full_name), assignee:assigned_to(id, full_name)")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .gte("created_at", f"{date_from}T00:00:00+00:00")
        .lte("created_at", f"{date_to}T23:59:59+00:00")
        .order("created_at", desc=False)
        .execute()
    )
    issues = issues_result.data or []
    if isinstance(issues, dict):
        issues = [issues]

    sales_result = (
        db.table("direct_sales")
        .select("sale_date, region, model, variant, units, amount, reconciliation_status, source_team")
        .eq("org_id", org_id)
        .gte("sale_date", date_from)
        .lte("sale_date", date_to)
        .execute()
    )
    sales = sales_result.data or []
    if isinstance(sales, dict):
        sales = [sales]

    # ── Executive summary (company-wide) ─────────────────────────────────────
    total_revenue = sum(float(s.get("amount") or 0) for s in sales)
    staff_logged_ids = {l.get("user_id") for l in logs if l.get("user_id")}
    users_result = db.table("users").select("id").eq("org_id", org_id).eq("is_active", True).execute()
    total_staff = len(users_result.data or [])
    total_issues = len(issues)
    open_issues = sum(1 for i in issues if i.get("status") != "resolved")
    resolved_issues = sum(1 for i in issues if i.get("status") == "resolved")

    # ── Build department -> team sections, dropping empty ones ──────────────
    def _build_team_section(team: dict) -> Optional[dict]:
        team_name = team["name"]
        team_logs = [l for l in logs if l.get("team") == team_name]
        team_issues = [i for i in issues if i.get("team") == team_name]
        team_sales_check = [s for s in sales if s.get("source_team") == team_name]

        if not team_logs and not team_issues and not team_sales_check:
            return None  # silently drop — genuinely nothing to show

        # Numeric team metrics only — text-type excluded per client decision
        metric_defs = [m for m in team_metrics_config if m.get("team_id") == team["id"] and m.get("field_type") == "number"]
        metric_totals = []
        for m in metric_defs:
            total = 0.0
            for log in team_logs:
                raw = (log.get("custom_metrics") or {}).get(m["id"])
                try:
                    total += float(raw)
                except (TypeError, ValueError):
                    pass
            metric_totals.append({"label": m["label"], "unit": m.get("unit"), "total": total})

        team_sales = team_sales_check
        sales_summary = None
        if team_sales:
            rev = sum(float(s.get("amount") or 0) for s in team_sales)
            units = sum(float(s.get("units") or 0) for s in team_sales)
            by_region: dict = {}
            for s in team_sales:
                r = s.get("region") or "Not recorded"
                by_region[r] = by_region.get(r, 0) + float(s.get("amount") or 0)
            sales_summary = {
                "revenue": rev,
                "units": units,
                "transactions": len(team_sales),
                "avg": rev / len(team_sales) if team_sales else 0,
                "by_region": sorted(by_region.items(), key=lambda x: x[1], reverse=True),
            }

        blockers = []
        for log in team_logs:
            for e in (log.get("entries") or []):
                if e.get("has_blocker"):
                    blockers.append({
                        "who": (log.get("user") or {}).get("full_name") or "—",
                        "date": log.get("log_date"),
                        "note": e.get("blocker_note"),
                        "status": e.get("blocker_issue_status") or "open",
                    })

        return {
            "team_name": team_name,
            "logs": team_logs,
            "issues": team_issues,
            "metric_totals": metric_totals,
            "sales_summary": sales_summary,
            "blockers": blockers,
        }

    department_sections = []
    for dept in departments:
        team_sections = []
        for team in teams_by_dept.get(dept["id"], []):
            sec = _build_team_section(team)
            if sec:
                team_sections.append(sec)
        if team_sections:
            department_sections.append({"name": dept["name"], "teams": team_sections})

    unassigned_sections = []
    for team in unassigned_teams:
        sec = _build_team_section(team)
        if sec:
            unassigned_sections.append(sec)

    # Per-department one-line highlights for the executive summary
    dept_highlights = []
    for dsec in department_sections:
        team_issue_count = sum(len(t["issues"]) for t in dsec["teams"])
        open_count = sum(1 for t in dsec["teams"] for i in t["issues"] if i.get("status") != "resolved")
        rev = sum((t["sales_summary"] or {}).get("revenue", 0) for t in dsec["teams"] if t["sales_summary"])
        if rev > 0:
            dept_highlights.append(f"{dsec['name']}: ₦{rev:,.0f} revenue, {open_count} open issue{'s' if open_count != 1 else ''}")
        else:
            dept_highlights.append(f"{dsec['name']}: {team_issue_count} issue{'s' if team_issue_count != 1 else ''}, {open_count} open")

    report_data = {
        "meta": {"org_name": org_name, "date_from": date_from, "date_to": date_to, "generated_at": now.isoformat()},
        "summary": {
            "total_revenue": total_revenue,
            "staff_logged": len(staff_logged_ids),
            "total_staff": total_staff,
            "total_issues": total_issues,
            "open_issues": open_issues,
            "resolved_issues": resolved_issues,
            "dept_highlights": dept_highlights,
        },
        "departments": department_sections,
        "unassigned": unassigned_sections,
    }

    pdf_bytes = _generate_business_activities_pdf(report_data)
    org_slug = org_name.replace(" ", "_")
    filename = f"Business_Activities_Report_{org_slug}_{date_from}_to_{date_to}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _generate_business_activities_pdf(report_data: dict) -> bytes:
    from weasyprint import HTML as _HTML

    meta = report_data["meta"]
    s    = report_data["summary"]

    def _fmt_naira(v) -> str:
        return f"₦{v:,.0f}"

    def _sta_colour(status: str) -> str:
        return {"open": AMBER, "in_progress": TEAL, "resolved": GREEN}.get((status or "").lower(), "#6b7280")

    def _pri_colour(p: str) -> str:
        return {"critical": RED, "high": AMBER, "medium": TEAL, "low": "#6b7280"}.get((p or "").lower(), "#6b7280")

    summary_html = f"""
    <div class='section'>
      <h2>Executive Summary</h2>
      <table>
        <thead><tr><th>Metric</th><th style='text-align:right'>Value</th></tr></thead>
        <tbody>
          <tr><td>Total Revenue</td><td style='text-align:right'><strong>{_fmt_naira(s['total_revenue'])}</strong></td></tr>
          <tr><td>Staff Logged</td><td style='text-align:right'>{s['staff_logged']} / {s['total_staff']}</td></tr>
          <tr><td>Total Issues</td><td style='text-align:right'>{s['total_issues']}</td></tr>
          <tr><td>Open Issues</td><td style='text-align:right;color:{AMBER}'>{s['open_issues']}</td></tr>
          <tr><td>Resolved Issues</td><td style='text-align:right;color:{GREEN}'>{s['resolved_issues']}</td></tr>
        </tbody>
      </table>
      {"<ul style='margin:8px 0 0;padding-left:18px'>" + "".join(f"<li style='font-size:9px;margin-bottom:3px'>{h}</li>" for h in s['dept_highlights']) + "</ul>" if s['dept_highlights'] else ""}
    </div>
    """

    def _render_team_section(team: dict) -> str:
        parts = [f"<h3 style='color:{TEAL};font-size:11px;margin:14px 0 6px'>{team['team_name']}</h3>"]

        if team["metric_totals"]:
            rows = "".join(
                f"<tr><td>{m['label']}</td><td style='text-align:right'>{m['total']:,.0f}{' ' + m['unit'] if m['unit'] else ''}</td></tr>"
                for m in team["metric_totals"]
            )
            parts.append(f"<table><thead><tr><th>Metric</th><th style='text-align:right'>Total</th></tr></thead><tbody>{rows}</tbody></table>")

        if team["sales_summary"]:
            ss = team["sales_summary"]
            region_rows = "".join(f"<tr><td>{r}</td><td style='text-align:right'>{_fmt_naira(v)}</td></tr>" for r, v in ss["by_region"])
            parts.append(f"""
            <table>
              <thead><tr><th>Sales Record</th><th style='text-align:right'>Value</th></tr></thead>
              <tbody>
                <tr><td>Revenue</td><td style='text-align:right'><strong>{_fmt_naira(ss['revenue'])}</strong></td></tr>
                <tr><td>Units Sold</td><td style='text-align:right'>{ss['units']:,.0f}</td></tr>
                <tr><td>Transactions</td><td style='text-align:right'>{ss['transactions']}</td></tr>
                <tr><td>Average Sale</td><td style='text-align:right'>{_fmt_naira(ss['avg'])}</td></tr>
                {region_rows}
              </tbody>
            </table>
            """)

        if team["blockers"]:
            b_rows = "".join(
                f"<tr><td>{b['who']}</td><td>{b['date']}</td>"
                f"<td style='color:{_sta_colour(b['status'] if b['status']=='resolved' else 'open')}'>{b['status'].replace('_',' ').title()}</td>"
                f"<td>{b['note'] or '—'}</td></tr>"
                for b in team["blockers"]
            )
            parts.append(f"""
            <table>
              <thead><tr><th>Blockers</th><th>Date</th><th>Status</th><th>Note</th></tr></thead>
              <tbody>{b_rows}</tbody>
            </table>
            """)

        if team["issues"]:
            i_rows = "".join(
                f"<tr><td style='color:{TEAL};font-weight:600'>{i.get('reference','—')}</td>"
                f"<td>{i.get('title','—')}</td>"
                f"<td style='color:{_pri_colour(i.get('priority'))}'>{(i.get('priority') or '').title()}</td>"
                f"<td style='color:{_sta_colour(i.get('status'))}'>{(i.get('status') or '').replace('_',' ').title()}</td></tr>"
                for i in team["issues"]
            )
            parts.append(f"""
            <table>
              <thead><tr><th>Issues</th><th>Title</th><th>Priority</th><th>Status</th></tr></thead>
              <tbody>{i_rows}</tbody>
            </table>
            """)

        if team["logs"]:
            log_html = ""
            for log in team["logs"]:
                who = (log.get("user") or {}).get("full_name") or "—"
                entries = log.get("entries") or []
                if entries:
                    entry_text = "<br>".join(
                        f"&bull; [{e.get('activity_type','General')}] {e.get('activity_description','')}"
                        for e in entries
                    )
                else:
                    entry_text = log.get("activities") or ""
                log_html += f"<p style='font-size:9px;margin:0 0 6px'><strong>{who}</strong> — {log.get('log_date')}<br>{entry_text}</p>"
            parts.append(f"<div style='margin-top:4px'><p style='font-size:9px;font-weight:700;color:{TEAL};margin:0 0 4px'>Activity Log</p>{log_html}</div>")

        return "".join(parts)

    dept_sections_html = ""
    for dept in report_data["departments"]:
        team_html = "".join(_render_team_section(t) for t in dept["teams"])
        dept_sections_html += f"<div class='section'><h2>{dept['name']}</h2>{team_html}</div>"

    if report_data["unassigned"]:
        team_html = "".join(_render_team_section(t) for t in report_data["unassigned"])
        dept_sections_html += f"<div class='section'><h2>Unassigned Teams</h2>{team_html}</div>"

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
      .section {{ page-break-inside: avoid; margin-bottom: 20px;
                  border-bottom: 1px solid #e5e7eb; padding-bottom: 14px; }}
      .section:last-child {{ border-bottom: none; }}
      h2       {{ font-size: 13px; color: {TEAL}; border-bottom: 1px solid #e5e7eb;
                  padding-bottom: 4px; margin-bottom: 8px; }}
      table    {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
      thead tr {{ background: {TEAL}; color: white; }}
      th       {{ padding: 5px 7px; text-align: left; font-size: 9px; }}
      td       {{ padding: 4px 7px; font-size: 9px; border-bottom: 1px solid #f3f4f6; }}
      tr:nth-child(even) td {{ background: #f9fafb; }}
    </style>
    </head>
    <body>
      <div class='header'>
        <div class='header-left'>
          <h1>Opsra</h1>
          <p>{meta['org_name']}</p>
          <p>Business Activities Report — {meta['date_from']} to {meta['date_to']}</p>
        </div>
        <div class='header-right'>Generated: {meta['generated_at'][:10]}</div>
      </div>
      {summary_html}
      {dept_sections_html or "<p>No department activity for this period.</p>"}
    </body>
    </html>
    """

    return _HTML(string=html).write_pdf()
