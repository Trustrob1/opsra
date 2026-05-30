"""
app/routers/internal_issues.py
OPS-1 — Internal Issue Tracker

Routes (static before parameterised — Pattern 53):
  GET    /internal-issues/summary   — counts by team + status (manager view)
  GET    /internal-issues           — list, filterable
  POST   /internal-issues           — create
  GET    /internal-issues/{id}      — single issue
  PATCH  /internal-issues/{id}      — update
  DELETE /internal-issues/{id}      — soft delete (owner/ops_manager only)

Security:
  Pattern 11 — JWT only (handled by get_current_org dependency)
  Pattern 12 — org_id never from payload, always from JWT via get_current_org
  Pattern 28 — get_current_org
  Pattern 62 — db via Depends(get_supabase)
  Pattern 53 — static routes before parameterised

No AI, no Celery workers, no WhatsApp hooks.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional, List
from pydantic import BaseModel
from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from datetime import datetime, timezone
import logging
import os
from fastapi.responses import Response

router = APIRouter()

logger = logging.getLogger(__name__)


def _check_ops_report_rate_limit(org_id: str) -> bool:
    """
    Enforce 10 PDF downloads per org per hour via Redis INCR.
    Returns True if allowed, False if limit exceeded.
    Fail open: returns True if Redis is unavailable (log warning only).
    """
    try:
        import redis as _redis
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return True
        r = _redis.from_url(url, decode_responses=True, socket_connect_timeout=1)
        key   = f"ops_report_download_limit:{org_id}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, 3600)
        return count <= 10
    except Exception as exc:
        logger.warning(
            "_check_ops_report_rate_limit: Redis unavailable — allowing download: %s", exc
        )
        return True

# ── Pydantic models ───────────────────────────────────────────────────────────

class IssueCreate(BaseModel):
    title: str
    description: Optional[str] = None
    team: str
    category: str
    priority: str = "medium"
    assigned_to: Optional[str] = None


class IssueUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    team: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    resolution_notes: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_manager(org: dict) -> bool:
    """True if the current user is owner or ops_manager."""
    template = (org.get("roles") or {}).get("template", "").lower()
    return template in ("owner", "ops_manager")


def _generate_reference(db, org_id: str) -> str:
    """Generate next ISS-NNN reference for this org."""
    result = (
        db.table("internal_issues")
        .select("reference")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        try:
            last_num = int(result.data[0]["reference"].split("-")[1])
            return f"ISS-{str(last_num + 1).zfill(3)}"
        except (IndexError, ValueError):
            pass
    return "ISS-001"


def _fetch_issue(db, issue_id: str, org_id: str) -> dict:
    """Fetch a single non-deleted issue. Raises 404 if not found."""
    result = (
        db.table("internal_issues")
        .select("*")
        .eq("id", issue_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Issue not found"},
        )
    data = result.data
    if isinstance(data, list):
        data = data[0]
    return data


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/internal-issues/report/download")
def download_internal_ops_report(
    date_from:     Optional[str] = None,
    date_to:       Optional[str] = None,
    team:          Optional[str] = None,
    category:      Optional[str] = None,
    status_filter: Optional[str] = None,
    priority:      Optional[str] = None,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1B: Generate and download Internal Ops Issues report as PDF.
    Filterable by date range, team, category, status, priority.
    Owner + ops_manager only. Rate limited: 10/hr via Redis. Fail open (S14).
    """
    if not _is_manager(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Manager access required"},
        )

    org_id = org["org_id"]

    if not _check_ops_report_rate_limit(org_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": "You can download up to 10 reports per hour.",
            },
        )

    now = datetime.now(timezone.utc)
    if not date_from:
        date_from = now.date().replace(day=1).isoformat()
    if not date_to:
        date_to = now.date().isoformat()

    query = (
        db.table("internal_issues")
        .select(
            "id, reference, title, description, team, category, priority, status, "
            "resolution_notes, resolved_at, created_at, updated_at, "
            "reporter:reported_by(id, full_name), assignee:assigned_to(id, full_name)"
        )
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .gte("created_at", f"{date_from}T00:00:00+00:00")
        .lte("created_at", f"{date_to}T23:59:59+00:00")
        .order("created_at", desc=False)
    )
    if team:          query = query.eq("team", team)
    if category:      query = query.eq("category", category)
    if status_filter: query = query.eq("status", status_filter)
    if priority:      query = query.eq("priority", priority)

    result = query.execute()
    issues = result.data or []
    if isinstance(issues, dict):
        issues = [issues]

    org_result = (
        db.table("organisations")
        .select("name")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    org_name_row = org_result.data
    if isinstance(org_name_row, list):
        org_name_row = org_name_row[0] if org_name_row else {}
    org_name = (org_name_row or {}).get("name") or "Organisation"

    total      = len(issues)
    open_count = sum(1 for i in issues if i.get("status") == "open")
    ip_count   = sum(1 for i in issues if i.get("status") == "in_progress")
    res_count  = sum(1 for i in issues if i.get("status") == "resolved")

    overdue_list = []
    for iss in issues:
        if iss.get("status") != "resolved":
            try:
                created = datetime.fromisoformat(iss["created_at"].replace("Z", "+00:00"))
                if (now - created).days >= 7:
                    overdue_list.append(iss)
            except Exception:
                pass

    resolution_rate = (res_count / total * 100) if total > 0 else 0.0

    team_map: dict = {}
    for iss in issues:
        t = iss.get("team") or "Unknown"
        if t not in team_map:
            team_map[t] = {"team": t, "total": 0, "open": 0,
                           "in_progress": 0, "resolved": 0, "_days": []}
        team_map[t]["total"] += 1
        s = iss.get("status", "open")
        if s in team_map[t]:
            team_map[t][s] += 1
        if s == "resolved" and iss.get("created_at") and iss.get("resolved_at"):
            try:
                c = datetime.fromisoformat(iss["created_at"].replace("Z", "+00:00"))
                r = datetime.fromisoformat(iss["resolved_at"].replace("Z", "+00:00"))
                team_map[t]["_days"].append((r - c).days)
            except Exception:
                pass
    by_team = []
    for td in team_map.values():
        days = td.pop("_days")
        td["avg_days_to_resolve"] = round(sum(days) / len(days), 1) if days else None
        by_team.append(td)
    by_team.sort(key=lambda x: x["total"], reverse=True)

    cat_map: dict = {}
    for iss in issues:
        c = iss.get("category") or "unknown"
        if c not in cat_map:
            cat_map[c] = {"category": c, "total": 0, "open": 0, "resolved": 0}
        cat_map[c]["total"] += 1
        if iss.get("status") == "open":     cat_map[c]["open"]     += 1
        if iss.get("status") == "resolved": cat_map[c]["resolved"] += 1
    by_category = []
    for cd in cat_map.values():
        cd["resolution_rate"] = (
            cd["resolved"] / cd["total"] * 100 if cd["total"] > 0 else 0.0
        )
        by_category.append(cd)
    by_category.sort(key=lambda x: x["total"], reverse=True)

    pri_order = ["critical", "high", "medium", "low"]
    pri_map: dict = {}
    for iss in issues:
        p = iss.get("priority") or "medium"
        if p not in pri_map:
            pri_map[p] = {"priority": p, "total": 0, "open": 0, "resolved": 0}
        pri_map[p]["total"] += 1
        if iss.get("status") == "open":     pri_map[p]["open"]     += 1
        if iss.get("status") == "resolved": pri_map[p]["resolved"] += 1
    by_priority = []
    for pd in sorted(
        pri_map.values(),
        key=lambda x: pri_order.index(x["priority"]) if x["priority"] in pri_order else 99,
    ):
        pd["resolution_rate"] = (
            pd["resolved"] / pd["total"] * 100 if pd["total"] > 0 else 0.0
        )
        by_priority.append(pd)

    report_data = {
        "meta": {
            "org_name":     org_name,
            "date_from":    date_from,
            "date_to":      date_to,
            "generated_at": now.isoformat(),
            "filters": {
                "team":     team,
                "category": category,
                "status":   status_filter,
                "priority": priority,
            },
        },
        "summary": {
            "total":           total,
            "open":            open_count,
            "in_progress":     ip_count,
            "resolved":        res_count,
            "overdue":         len(overdue_list),
            "resolution_rate": resolution_rate,
        },
        "by_team":     by_team,
        "by_category": by_category,
        "by_priority": by_priority,
        "overdue":     overdue_list,
        "issues":      issues,
    }

    pdf_bytes = _generate_internal_ops_pdf(report_data)
    org_slug  = org_name.replace(" ", "_")
    filename  = f"Internal_Ops_Report_{org_slug}_{date_from}_to_{date_to}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _generate_internal_ops_pdf(report_data: dict) -> bytes:
    """
    OPS-1B: Render internal issues report to branded PDF via WeasyPrint.
    Raises ValueError if report_data missing meta. Returns raw PDF bytes.
    """
    if not report_data.get("meta"):
        raise ValueError("_generate_internal_ops_pdf: report_data is missing meta")

    from weasyprint import HTML as _HTML

    meta      = report_data["meta"]
    org_name  = meta.get("org_name") or "Organisation"
    date_from = meta.get("date_from") or ""
    date_to   = meta.get("date_to") or ""
    gen_at    = meta.get("generated_at") or ""
    filters   = meta.get("filters") or {}

    TEAL  = "#0D9488"
    RED   = "#dc2626"
    AMBER = "#d97706"
    GREEN = "#16a34a"

    def _fmt(val) -> str:
        if val is None: return "—"
        return str(val)

    def _fmt_date(iso) -> str:
        if not iso: return "—"
        try:    return str(iso)[:10]
        except: return str(iso)

    def _pri_colour(p: str) -> str:
        return {"critical": RED, "high": AMBER, "medium": TEAL, "low": "#6b7280"}.get(
            (p or "").lower(), "#6b7280"
        )

    def _sta_colour(s: str) -> str:
        return {"open": AMBER, "in_progress": TEAL, "resolved": GREEN}.get(
            (s or "").lower(), "#6b7280"
        )

    fp = []
    if filters.get("team"):     fp.append(f"Team: {filters['team']}")
    if filters.get("category"): fp.append(f"Category: {filters['category']}")
    if filters.get("status"):   fp.append(f"Status: {filters['status']}")
    if filters.get("priority"): fp.append(f"Priority: {filters['priority']}")
    filter_line = "  ·  ".join(fp) if fp else "All issues"

    s  = report_data.get("summary") or {}
    rr = s.get("resolution_rate", 0)
    rr_colour = GREEN if rr >= 75 else AMBER if rr >= 50 else RED

    summary_html = f"""
    <div class='section'>
      <h2>Summary</h2>
      <table>
        <thead><tr><th>Metric</th><th style='text-align:right'>Value</th></tr></thead>
        <tbody>
          <tr><td>Total Issues</td>
              <td style='text-align:right'><strong>{_fmt(s.get('total'))}</strong></td></tr>
          <tr><td>Open</td>
              <td style='text-align:right;color:{AMBER}'>{_fmt(s.get('open'))}</td></tr>
          <tr><td>In Progress</td>
              <td style='text-align:right;color:{TEAL}'>{_fmt(s.get('in_progress'))}</td></tr>
          <tr><td>Resolved</td>
              <td style='text-align:right;color:{GREEN}'>{_fmt(s.get('resolved'))}</td></tr>
          <tr><td>Overdue (&gt;7 days unresolved)</td>
              <td style='text-align:right;color:{RED}'><strong>{_fmt(s.get('overdue'))}</strong></td></tr>
          <tr><td>Resolution Rate</td>
              <td style='text-align:right;color:{rr_colour}'><strong>{rr:.1f}%</strong></td></tr>
        </tbody>
      </table>
    </div>
    """

    by_team   = report_data.get("by_team") or []
    team_rows = ""
    for t in by_team:
        avg = _fmt(t.get("avg_days_to_resolve"))
        avg_str = f"{avg} days" if avg != "—" else "—"
        team_rows += (
            f"<tr><td>{_fmt(t.get('team'))}</td>"
            f"<td style='text-align:right'>{_fmt(t.get('total'))}</td>"
            f"<td style='text-align:right;color:{AMBER}'>{_fmt(t.get('open'))}</td>"
            f"<td style='text-align:right;color:{TEAL}'>{_fmt(t.get('in_progress'))}</td>"
            f"<td style='text-align:right;color:{GREEN}'>{_fmt(t.get('resolved'))}</td>"
            f"<td style='text-align:right'>{avg_str}</td></tr>"
        )
    team_html = f"""
    <div class='section'>
      <h2>Issues by Team</h2>
      <table>
        <thead><tr>
          <th>Team</th><th>Total</th><th>Open</th>
          <th>In Progress</th><th>Resolved</th><th>Avg Days to Resolve</th>
        </tr></thead>
        <tbody>{team_rows or "<tr><td colspan='6'>No data</td></tr>"}</tbody>
      </table>
    </div>
    """ if by_team else ""

    by_cat   = report_data.get("by_category") or []
    cat_rows = ""
    for c in by_cat:
        label = (c.get("category") or "").replace("_", " ").title()
        cat_rows += (
            f"<tr><td>{label}</td>"
            f"<td style='text-align:right'>{_fmt(c.get('total'))}</td>"
            f"<td style='text-align:right;color:{AMBER}'>{_fmt(c.get('open'))}</td>"
            f"<td style='text-align:right;color:{GREEN}'>{_fmt(c.get('resolved'))}</td>"
            f"<td style='text-align:right'>{c.get('resolution_rate', 0):.1f}%</td></tr>"
        )
    cat_html = f"""
    <div class='section'>
      <h2>Issues by Category</h2>
      <table>
        <thead><tr>
          <th>Category</th><th>Total</th><th>Open</th>
          <th>Resolved</th><th>Resolution Rate</th>
        </tr></thead>
        <tbody>{cat_rows or "<tr><td colspan='5'>No data</td></tr>"}</tbody>
      </table>
    </div>
    """ if by_cat else ""

    by_pri   = report_data.get("by_priority") or []
    pri_rows = ""
    for p in by_pri:
        pri_rows += (
            f"<tr>"
            f"<td style='color:{_pri_colour(p.get(\"priority\",\"\"))};font-weight:600'>"
            f"{(p.get('priority') or '').title()}</td>"
            f"<td style='text-align:right'>{_fmt(p.get('total'))}</td>"
            f"<td style='text-align:right;color:{AMBER}'>{_fmt(p.get('open'))}</td>"
            f"<td style='text-align:right;color:{GREEN}'>{_fmt(p.get('resolved'))}</td>"
            f"<td style='text-align:right'>{p.get('resolution_rate', 0):.1f}%</td></tr>"
        )
    pri_html = f"""
    <div class='section'>
      <h2>Issues by Priority</h2>
      <table>
        <thead><tr>
          <th>Priority</th><th>Total</th><th>Open</th>
          <th>Resolved</th><th>Resolution Rate</th>
        </tr></thead>
        <tbody>{pri_rows or "<tr><td colspan='5'>No data</td></tr>"}</tbody>
      </table>
    </div>
    """ if by_pri else ""

    overdue      = report_data.get("overdue") or []
    overdue_html = ""
    if overdue:
        od_rows = ""
        now_utc = datetime.now(timezone.utc)
        for iss in overdue:
            days_open = "—"
            try:
                c = datetime.fromisoformat(iss["created_at"].replace("Z", "+00:00"))
                days_open = str((now_utc - c).days)
            except Exception:
                pass
            od_rows += (
                f"<tr>"
                f"<td style='color:{TEAL};font-weight:600'>{_fmt(iss.get('reference'))}</td>"
                f"<td>{_fmt(iss.get('title'))}</td>"
                f"<td>{_fmt(iss.get('team'))}</td>"
                f"<td style='color:{_pri_colour(iss.get(\"priority\",\"\"))};font-weight:600'>"
                f"{(iss.get('priority') or '').title()}</td>"
                f"<td style='color:{RED};font-weight:600'>{days_open} days</td></tr>"
            )
        overdue_html = f"""
        <div class='section'>
          <h2 style='color:{RED}'>&#9888; Overdue Issues ({len(overdue)})</h2>
          <p style='font-size:9px;color:{RED};margin:0 0 8px'>
            Unresolved for more than 7 days
          </p>
          <table>
            <thead><tr>
              <th>Ref</th><th>Title</th><th>Team</th>
              <th>Priority</th><th>Days Open</th>
            </tr></thead>
            <tbody>{od_rows}</tbody>
          </table>
        </div>
        """

    issues     = report_data.get("issues") or []
    issue_rows = ""
    for iss in issues:
        reporter = (iss.get("reporter") or {}).get("full_name") or "—"
        assignee = (iss.get("assignee") or {}).get("full_name") or "—"
        issue_rows += (
            f"<tr>"
            f"<td style='color:{TEAL};font-weight:600;white-space:nowrap'>"
            f"{_fmt(iss.get('reference'))}</td>"
            f"<td style='max-width:180px'>{_fmt(iss.get('title'))}</td>"
            f"<td>{_fmt(iss.get('team'))}</td>"
            f"<td>{(iss.get('category') or '').replace('_',' ').title()}</td>"
            f"<td style='color:{_pri_colour(iss.get(\"priority\",\"\"))};font-weight:600'>"
            f"{(iss.get('priority') or '').title()}</td>"
            f"<td style='color:{_sta_colour(iss.get(\"status\",\"\"))};font-weight:600'>"
            f"{(iss.get('status') or '').replace('_',' ').title()}</td>"
            f"<td>{reporter}</td>"
            f"<td>{assignee}</td>"
            f"<td style='white-space:nowrap'>{_fmt_date(iss.get('created_at'))}</td>"
            f"<td style='white-space:nowrap'>{_fmt_date(iss.get('resolved_at'))}</td>"
            f"</tr>"
        )
    issues_html = f"""
    <div class='section'>
      <h2>Full Issue Log ({len(issues)} issues)</h2>
      <table>
        <thead><tr>
          <th>Ref</th><th>Title</th><th>Team</th><th>Category</th>
          <th>Priority</th><th>Status</th><th>Reported By</th>
          <th>Assigned To</th><th>Opened</th><th>Resolved</th>
        </tr></thead>
        <tbody>
          {issue_rows or "<tr><td colspan='10'>No issues match the selected filters.</td></tr>"}
        </tbody>
      </table>
    </div>
    """

    sections_html = (
        summary_html + team_html + cat_html + pri_html + overdue_html + issues_html
    )

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
      .section {{ page-break-inside: avoid; margin-bottom: 24px;
                  border-bottom: 1px solid #e5e7eb; padding-bottom: 16px; }}
      .section:last-child {{ border-bottom: none; }}
      h2       {{ font-size: 13px; color: {TEAL}; border-bottom: 1px solid #e5e7eb;
                  padding-bottom: 4px; margin-bottom: 8px; }}
      p        {{ margin: 0 0 8px; font-size: 10px; color: #6b7280; }}
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
          <p>{org_name}</p>
          <p>Internal Ops Report — {date_from} to {date_to}</p>
          <p style='color:#9ca3af;font-size:9px'>{filter_line}</p>
        </div>
        <div class='header-right'>
          Generated: {gen_at[:10] if gen_at else ''}
        </div>
      </div>
      {sections_html}
    </body>
    </html>
    """

    return _HTML(string=html).write_pdf()


@router.get("/internal-issues/summary")
def get_issues_summary(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Return issue counts by status and by team.
    All roles: scoped to own team unless owner/ops_manager.
    """
    org_id = org["org_id"]
    user_id = org["id"]
    manager = _is_manager(org)

    query = (
        db.table("internal_issues")
        .select("status, team, created_at")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
    )
    if not manager:
        # non-managers scoped to their own team
        user_team = org.get("team") or ""
        if user_team:
            query = query.eq("team", user_team)
        else:
            # user has no team — return empty summary
            return ok(data={"by_status": {}, "by_team": {}, "overdue": 0})

    result = query.execute()
    issues = result.data or []

    by_status = {"open": 0, "in_progress": 0, "resolved": 0}
    by_team: dict = {}
    overdue = 0

    cutoff = datetime.now(timezone.utc)

    for iss in issues:
        s = iss.get("status", "open")
        if s in by_status:
            by_status[s] += 1

        t = iss.get("team", "")
        if t not in by_team:
            by_team[t] = {"open": 0, "in_progress": 0, "resolved": 0}
        if s in by_team[t]:
            by_team[t][s] += 1

        # Overdue: unresolved + older than 7 days
        if s != "resolved":
            try:
                created = datetime.fromisoformat(iss["created_at"].replace("Z", "+00:00"))
                if (cutoff - created).days >= 7:
                    overdue += 1
            except Exception:
                pass

    return ok(data={"by_status": by_status, "by_team": by_team, "overdue": overdue})


@router.get("/internal-issues")
def list_issues(
    team: Optional[str] = None,
    status_filter: Optional[str] = None,
    assigned_to: Optional[str] = None,
    reported_by: Optional[str] = None,
    priority: Optional[str] = None,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: List issues. Non-managers scoped to own team.
    Filterable by team, status, assigned_to, reported_by, priority.
    """
    org_id = org["org_id"]
    manager = _is_manager(org)

    query = (
        db.table("internal_issues")
        .select("*, reporter:reported_by(id, full_name), assignee:assigned_to(id, full_name)")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
    )

    if not manager:
        user_team = org.get("team") or ""
        query = query.eq("team", user_team)
    elif team:
        query = query.eq("team", team)

    if status_filter:
        query = query.eq("status", status_filter)
    if assigned_to:
        query = query.eq("assigned_to", assigned_to)
    if reported_by:
        query = query.eq("reported_by", reported_by)
    if priority:
        query = query.eq("priority", priority)

    result = query.execute()
    issues = result.data or []
    if isinstance(issues, dict):
        issues = [issues]

    return ok(data={"items": issues, "total": len(issues)})


@router.post("/internal-issues")
def create_issue(
    payload: IssueCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Create a new internal issue.
    reported_by always set from current user — never from payload.
    """
    org_id = org["org_id"]
    user_id = org["id"]

    if not payload.title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Title is required"},
        )
    if not payload.team.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Team is required"},
        )
    if not payload.category.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Category is required"},
        )

    reference = _generate_reference(db, org_id)

    row = {
        "org_id":      org_id,
        "reference":   reference,
        "title":       payload.title.strip(),
        "description": payload.description,
        "team":        payload.team.strip(),
        "category":    payload.category.strip(),
        "priority":    payload.priority,
        "status":      "open",
        "reported_by": user_id,
        "assigned_to": payload.assigned_to or None,
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }

    result = db.table("internal_issues").insert(row).execute()
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else row

    return ok(data=data, message="Issue created")


@router.get("/internal-issues/{issue_id}")
def get_issue(
    issue_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """OPS-1: Get a single issue by ID."""
    org_id = org["org_id"]
    manager = _is_manager(org)
    issue = _fetch_issue(db, issue_id, org_id)

    # Non-managers can only view issues from their own team
    if not manager:
        user_team = org.get("team") or ""
        if issue.get("team") != user_team:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "Access denied"},
            )

    return ok(data=issue)


@router.patch("/internal-issues/{issue_id}")
def update_issue(
    issue_id: str,
    payload: IssueUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Update an issue.
    Managers can update any field on any issue in their org.
    Non-managers can update status/resolution_notes on issues assigned to them.
    auto-sets resolved_at when status → resolved; clears it when status reverts.
    """
    org_id = org["org_id"]
    user_id = org["id"]
    manager = _is_manager(org)
    issue = _fetch_issue(db, issue_id, org_id)

    # RBAC: non-manager can only update their assigned issues
    if not manager:
        if issue.get("assigned_to") != user_id and issue.get("reported_by") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "You can only update issues assigned to or reported by you"},
            )

    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "No fields provided to update"},
        )

    # Auto-manage resolved_at
    new_status = update_data.get("status")
    if new_status == "resolved" and not issue.get("resolved_at"):
        update_data["resolved_at"] = datetime.now(timezone.utc).isoformat()
    elif new_status in ("open", "in_progress") and issue.get("resolved_at"):
        update_data["resolved_at"] = None

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        db.table("internal_issues")
        .update(update_data)
        .eq("id", issue_id)
        .eq("org_id", org_id)
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else update_data

    return ok(data=data, message="Issue updated")


@router.delete("/internal-issues/{issue_id}")
def delete_issue(
    issue_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """OPS-1: Soft-delete an issue. Owner/ops_manager only."""
    org_id = org["org_id"]

    if not _is_manager(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can delete issues"},
        )

    _fetch_issue(db, issue_id, org_id)  # confirms exists and belongs to org

    db.table("internal_issues").update({
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", issue_id).eq("org_id", org_id).execute()

    return ok(data={"id": issue_id}, message="Issue deleted")
