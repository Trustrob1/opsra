"""
app/routers/activity_logs.py
OPS-1 — Daily / Weekly Activity Log

Routes (static before parameterised — Pattern 53):
  GET    /activity-logs/summary   — weekly rollup per team member (manager view)
  POST   /activity-logs           — create or update (upsert on unique key)
  GET    /activity-logs           — list, filterable
  PATCH  /activity-logs/{id}      — edit own log only

Security:
  Pattern 11 — JWT only
  Pattern 12 — org_id, user_id, team never from payload — always from JWT
  Pattern 28 — get_current_org
  Pattern 53 — static routes before parameterised
  Pattern 62 — db via Depends(get_supabase)

No AI, no Celery workers, no WhatsApp hooks.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from typing import Optional
from pydantic import BaseModel
from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.routers.internal_issues import _generate_reference
from datetime import datetime, timezone, timedelta, date
import logging
import os

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

class ActivityLogCreate(BaseModel):
    log_date: str        # ISO date string "YYYY-MM-DD"
    log_type: str = "daily"
    activities: str
    blockers: Optional[str] = None
    plan: Optional[str] = None


class ActivityLogUpdate(BaseModel):
    activities: Optional[str] = None
    blockers: Optional[str] = None
    plan: Optional[str] = None


class ActivityEntry(BaseModel):
    activity_description: str
    activity_type:        str = "General"
    duration_minutes:     Optional[int] = None
    has_blocker:          bool = False
    blocker_note:         Optional[str] = None
    plan:                 Optional[str] = None


class ActivityLogBulkCreate(BaseModel):
    log_date:  str
    log_type:  str = "daily"
    entries:   list[ActivityEntry]

# ── Helper ────────────────────────────────────────────────────────────────────

def _is_manager(org: dict) -> bool:
    template = (org.get("roles") or {}).get("template", "").lower()
    return template in ("owner", "ops_manager")


def _week_start(iso_date: str) -> str:
    """Return the ISO Monday of the week containing iso_date."""
    d = date.fromisoformat(iso_date)
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


# ── Rate limit helper ─────────────────────────────────────────────────────────

def _check_activity_log_report_rate_limit(org_id: str) -> bool:
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
        key   = f"activity_log_report_limit:{org_id}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, 3600)
        return count <= 10
    except Exception as exc:
        logger.warning(
            "_check_activity_log_report_rate_limit: Redis unavailable — allowing download: %s", exc
        )
        return True


# ── PDF generator ─────────────────────────────────────────────────────────────

def _generate_activity_log_pdf(report_data: dict) -> bytes:
    """
    OPS-2: Render activity log report to branded PDF via WeasyPrint.
    S14: never raises — returns error-page PDF on any failure.
    """
    from weasyprint import HTML as _HTML

    TEAL  = "#0D9488"
    RED   = "#dc2626"
    AMBER = "#d97706"
    GREEN = "#16a34a"

    def _fmt(val) -> str:
        if val is None: return "—"
        return str(val)

    def _fmt_date(iso) -> str:
        if not iso: return "—"
        try:
            d = str(iso)[:10]
            from datetime import date as _date
            parsed = _date.fromisoformat(d)
            return parsed.strftime("%-d %b %Y")
        except Exception:
            return str(iso)[:10]

    try:
        meta      = report_data.get("meta") or {}
        org_name  = meta.get("org_name") or "Organisation"
        date_from = meta.get("date_from") or ""
        date_to   = meta.get("date_to") or ""
        gen_at    = meta.get("generated_at") or ""
        gen_by    = meta.get("generated_by") or ""
        filter_label = meta.get("filter_label") or "All staff"

        summary   = report_data.get("summary") or {}
        per_staff = report_data.get("per_staff") or []
        log_rows  = report_data.get("log_rows") or []
        blocker_rows      = report_data.get("blocker_rows") or []
        contractor_rows   = report_data.get("contractor_rows") or []
        contractor_blockers = report_data.get("contractor_blocker_rows") or []
        include_contractors = report_data.get("include_contractors", False)
        is_manager = report_data.get("is_manager", True)

        # ── Section 1: KPI strip ───────────────────────────────────────────────
        total_activities = summary.get("total_activities", 0)
        total_hours      = summary.get("total_hours", 0)
        total_blockers   = summary.get("total_blockers", 0)
        staff_active     = summary.get("staff_active", 0)
        contractor_count = summary.get("contractor_count", 0)

        # Build KPI boxes — add contractor box when included
        _blocker_colour = RED if total_blockers > 0 else "#111827"
        kpi_boxes = (
            f"<td class='kpi-box'>"
            f"<div class='kpi-num'>{total_activities}</div>"
            f"<div class='kpi-lbl'>Activities logged</div>"
            f"</td>"
            f"<td class='kpi-box'>"
            f"<div class='kpi-num'>{total_hours}h</div>"
            f"<div class='kpi-lbl'>Total hours</div>"
            f"</td>"
            f"<td class='kpi-box'>"
            f"<div class='kpi-num' style='color:{_blocker_colour}'>{total_blockers}</div>"
            f"<div class='kpi-lbl'>Blockers raised</div>"
            f"</td>"
            f"<td class='kpi-box'>"
            f"<div class='kpi-num'>{staff_active}</div>"
            f"<div class='kpi-lbl'>Staff active</div>"
            f"</td>"
        )
        if include_contractors and contractor_count > 0:
            kpi_boxes += (
                f"<td class='kpi-box'>"
                f"<div class='kpi-num' style='color:#7c3aed'>{contractor_count}</div>"
                f"<div class='kpi-lbl'>Contractors active</div>"
                f"</td>"
            )

        kpi_html = f"""
        <div class='section'>
          <table class='kpi-table'>
            <tr>{kpi_boxes}</tr>
          </table>
        </div>
        """

        # ── Section 2: Per-staff summary table (manager only) ─────────────────
        staff_html = ""
        if is_manager and per_staff:
            staff_rows = ""
            for s in per_staff:
                _bc = s.get("blockers", 0)
                blocker_cell = (
                    f"<td style='text-align:right;color:{RED};font-weight:600'>{_bc}</td>"
                    if _bc > 0
                    else f"<td style='text-align:right;color:#6b7280'>{_bc}</td>"
                )
                staff_rows += (
                    f"<tr>"
                    f"<td style='font-weight:600'>{_fmt(s.get('full_name'))}</td>"
                    f"<td>{_fmt(s.get('team'))}</td>"
                    f"<td style='text-align:right'>{_fmt(s.get('days_logged'))}</td>"
                    f"<td style='text-align:right'>{_fmt(s.get('activities'))}</td>"
                    f"<td style='text-align:right'>{_fmt(s.get('hours'))}h</td>"
                    f"{blocker_cell}"
                    f"</tr>"
                )
            staff_html = f"""
            <div class='section'>
              <h2>Staff summary</h2>
              <table>
                <thead><tr>
                  <th>Staff</th><th>Team</th><th style='text-align:right'>Days logged</th>
                  <th style='text-align:right'>Activities</th>
                  <th style='text-align:right'>Hours</th>
                  <th style='text-align:right'>Blockers</th>
                </tr></thead>
                <tbody>{staff_rows}</tbody>
              </table>
            </div>
            """

        # ── Section 3: Detailed activity log ──────────────────────────────────
        detail_rows = ""
        current_staff = None
        for row in log_rows:
            _staff_name = row.get("full_name") or "—"
            # Staff group heading when staff changes
            if _staff_name != current_staff:
                current_staff = _staff_name
                _team = row.get("team") or ""
                detail_rows += (
                    f"<tr class='staff-heading'>"
                    f"<td colspan='4' style='background:#f0fdfa;color:{TEAL};"
                    f"font-weight:700;font-size:10px;padding:7px 7px 5px'>"
                    f"{_staff_name}"
                    f"<span style='font-weight:400;color:#6b7280;margin-left:8px'>{_team}</span>"
                    f"</td></tr>"
                )

            _date_str  = _fmt_date(row.get("log_date"))
            _act_type  = (row.get("activity_type") or "General").strip()
            _desc      = (row.get("activity_description") or row.get("activities") or "").strip()
            _hrs_raw   = row.get("duration_minutes")
            _hrs       = f"{_hrs_raw}h" if _hrs_raw else "—"
            _has_blocker = row.get("has_blocker", False)
            _blocker_note = (row.get("blocker_note") or "").strip()

            # Activity cell: description + optional blocker callout
            act_cell = f"<div style='font-weight:600;font-size:9px;margin-bottom:3px'>{_desc}</div>"
            if _has_blocker and _blocker_note:
                act_cell += (
                    f"<div style='margin-top:4px;padding:4px 6px;"
                    f"background:#fef2f2;border-left:2px solid {RED};"
                    f"font-size:8.5px;color:{RED};line-height:1.4'>"
                    f"&#9888; Blocker: {_blocker_note}</div>"
                )
            elif _has_blocker:
                act_cell += (
                    f"<div style='margin-top:4px;padding:4px 6px;"
                    f"background:#fef2f2;border-left:2px solid {RED};"
                    f"font-size:8.5px;color:{RED}'>"
                    f"&#9888; Blocker (no details provided)</div>"
                )

            _row_bg = "background:#fff8f8;" if _has_blocker else ""
            detail_rows += (
                f"<tr style='{_row_bg}'>"
                f"<td style='white-space:nowrap;color:#374151;font-size:9px'>{_date_str}</td>"
                f"<td><span style='background:#e0f2fe;color:#0369a1;border-radius:10px;"
                f"padding:2px 7px;font-size:8px;font-weight:600;white-space:nowrap'>"
                f"{_act_type}</span></td>"
                f"<td>{act_cell}</td>"
                f"<td style='text-align:right;font-weight:600;font-size:9px;"
                f"white-space:nowrap;color:#374151'>{_hrs}</td>"
                f"</tr>"
            )

        detail_html = f"""
        <div class='section'>
          <h2>Detailed activity log</h2>
          <table>
            <thead><tr>
              <th style='width:12%'>Date</th>
              <th style='width:13%'>Type</th>
              <th style='width:65%'>Activity &amp; notes</th>
              <th style='width:10%;text-align:right'>Hrs</th>
            </tr></thead>
            <tbody>
              {detail_rows or "<tr><td colspan='4' style='color:#6b7280'>No activity logs match the selected filters.</td></tr>"}
            </tbody>
          </table>
        </div>
        """ if log_rows else f"""
        <div class='section'>
          <p style='color:#6b7280'>No activity logs match the selected filters.</p>
        </div>
        """

        # ── Section 4: Blockers summary (manager only) ─────────────────────────
        blockers_html = ""
        if is_manager and blocker_rows:
            bl_rows = ""
            for b in blocker_rows:
                bl_rows += (
                    f"<tr>"
                    f"<td style='font-weight:600'>{_fmt(b.get('full_name'))}</td>"
                    f"<td style='white-space:nowrap;font-size:9px'>{_fmt_date(b.get('log_date'))}</td>"
                    f"<td style='color:{RED}'>{_fmt(b.get('blocker_note'))}</td>"
                    f"</tr>"
                )
            blockers_html = f"""
            <div class='section'>
              <h2 style='color:{RED}'>&#9888; Blockers summary ({len(blocker_rows)})</h2>
              <table>
                <thead><tr>
                  <th>Staff</th><th>Date</th><th>Blocker description</th>
                </tr></thead>
                <tbody>{bl_rows}</tbody>
              </table>
            </div>
            """

        sections_html = kpi_html + staff_html + detail_html + blockers_html

        # ── Section 5: Contractor daily activities ─────────────────────────────
        contractor_html = ""
        if include_contractors and contractor_rows:
            contr_detail_rows = ""
            current_contractor = None
            for row in contractor_rows:
                _cname = row.get("contractor_name") or "—"
                if _cname != current_contractor:
                    current_contractor = _cname
                    _role = row.get("contractor_role") or ""
                    contr_detail_rows += (
                        f"<tr class='staff-heading'>"
                        f"<td colspan='4' style='background:#fdf4ff;color:#7c3aed;"
                        f"font-weight:700;font-size:10px;padding:7px 7px 5px'>"
                        f"{_cname}"
                        f"<span style='font-weight:400;color:#6b7280;margin-left:8px'>"
                        f"{_role}</span>"
                        f"</td></tr>"
                    )

                _date_str     = _fmt_date(row.get("log_date"))
                _act_type     = (row.get("activity_type") or "General").strip()
                _desc         = (row.get("activity_description") or "").strip()
                _hrs_raw      = row.get("duration_minutes")
                _hrs          = f"{_hrs_raw}h" if _hrs_raw else "—"
                _has_blocker  = row.get("has_blocker", False)
                _blocker_note = (row.get("blocker_note") or "").strip()
                _resolved     = bool(row.get("resolved_at"))

                act_cell = f"<div style='font-weight:600;font-size:9px;margin-bottom:3px'>{_desc}</div>"
                if _has_blocker and _blocker_note:
                    _bl_bg    = "#f0fdf4" if _resolved else "#fef2f2"
                    _bl_bord  = "#16a34a" if _resolved else RED
                    _bl_col   = "#16a34a" if _resolved else RED
                    _bl_label = "&#10003; Blocker resolved" if _resolved else "&#9888; Blocker"
                    act_cell += (
                        f"<div style='margin-top:4px;padding:4px 6px;"
                        f"background:{_bl_bg};border-left:2px solid {_bl_bord};"
                        f"font-size:8.5px;color:{_bl_col};line-height:1.4'>"
                        f"{_bl_label}: {_blocker_note}</div>"
                    )
                elif _has_blocker:
                    _bl_bg   = "#f0fdf4" if _resolved else "#fef2f2"
                    _bl_bord = "#16a34a" if _resolved else RED
                    _bl_col  = "#16a34a" if _resolved else RED
                    _bl_label = "&#10003; Blocker resolved" if _resolved else "&#9888; Blocker"
                    act_cell += (
                        f"<div style='margin-top:4px;padding:4px 6px;"
                        f"background:{_bl_bg};border-left:2px solid {_bl_bord};"
                        f"font-size:8.5px;color:{_bl_col}'>"
                        f"{_bl_label} (no details provided)</div>"
                    )

                _row_bg = "background:#fff8f8;" if (_has_blocker and not _resolved) else ""
                contr_detail_rows += (
                    f"<tr style='{_row_bg}'>"
                    f"<td style='white-space:nowrap;color:#374151;font-size:9px'>{_date_str}</td>"
                    f"<td><span style='background:#f3e8ff;color:#7c3aed;border-radius:10px;"
                    f"padding:2px 7px;font-size:8px;font-weight:600;white-space:nowrap'>"
                    f"{_act_type}</span></td>"
                    f"<td>{act_cell}</td>"
                    f"<td style='text-align:right;font-weight:600;font-size:9px;"
                    f"white-space:nowrap;color:#374151'>{_hrs}</td>"
                    f"</tr>"
                )

            # Contractor blocker summary
            contr_blocker_html = ""
            if is_manager and contractor_blockers:
                cb_rows = ""
                for b in contractor_blockers:
                    _resolved_str = (
                        f"<span style='color:#16a34a;font-weight:600'>&#10003; Resolved</span>"
                        if b.get("resolved_at")
                        else f"<span style='color:{RED}'>Open</span>"
                    )
                    cb_rows += (
                        f"<tr>"
                        f"<td style='font-weight:600'>{_fmt(b.get('contractor_name'))}</td>"
                        f"<td style='white-space:nowrap;font-size:9px'>{_fmt_date(b.get('log_date'))}</td>"
                        f"<td style='color:{RED}'>{_fmt(b.get('blocker_note'))}</td>"
                        f"<td>{_resolved_str}</td>"
                        f"</tr>"
                    )
                contr_blocker_html = f"""
                <div class='section' style='margin-top:12px'>
                  <h2 style='color:{RED}'>&#9888; Contractor blockers ({len(contractor_blockers)})</h2>
                  <table>
                    <thead><tr>
                      <th>Contractor</th><th>Date</th>
                      <th>Blocker description</th><th>Status</th>
                    </tr></thead>
                    <tbody>{cb_rows}</tbody>
                  </table>
                </div>
                """

            contractor_html = f"""
            <div class='section'>
              <h2 style='color:#7c3aed'>Contractor daily activities</h2>
              <table>
                <thead><tr>
                  <th style='width:12%'>Date</th>
                  <th style='width:13%'>Type</th>
                  <th style='width:65%'>Activity &amp; notes</th>
                  <th style='width:10%;text-align:right'>Hrs</th>
                </tr></thead>
                <tbody>{contr_detail_rows}</tbody>
              </table>
            </div>
            {contr_blocker_html}
            """

        sections_html = kpi_html + staff_html + detail_html + blockers_html + contractor_html

        html = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8">
        <style>
          @page {{
            margin: 20mm 15mm;
            @bottom-center {{
              content: "Page " counter(page) " of " counter(pages) "  |  Opsra  ·  {org_name}";
              font-size: 8px; color: #6b7280;
            }}
          }}
          body       {{ font-family: Arial, sans-serif; font-size: 10px; color: #111827; margin: 0; }}
          .header    {{ border-bottom: 2px solid {TEAL}; padding-bottom: 8px; margin-bottom: 16px;
                        display: flex; justify-content: space-between; align-items: flex-start; }}
          .header-left h1  {{ margin: 0; font-size: 18px; color: {TEAL}; }}
          .header-left p   {{ margin: 2px 0; font-size: 10px; color: #6b7280; }}
          .header-right    {{ text-align: right; font-size: 9px; color: #6b7280; }}
          .section   {{ page-break-inside: avoid; margin-bottom: 24px;
                        border-bottom: 1px solid #e5e7eb; padding-bottom: 16px; }}
          .section:last-child {{ border-bottom: none; }}
          h2         {{ font-size: 13px; color: {TEAL}; border-bottom: 1px solid #e5e7eb;
                        padding-bottom: 4px; margin-bottom: 8px; }}
          p          {{ margin: 0 0 8px; font-size: 10px; color: #6b7280; }}
          table      {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
          thead tr   {{ background: {TEAL}; color: white; }}
          th         {{ padding: 5px 7px; text-align: left; font-size: 9px; font-weight: 600; }}
          td         {{ padding: 5px 7px; font-size: 9px; border-bottom: 1px solid #f3f4f6;
                        vertical-align: top; }}
          tr:nth-child(even) td {{ background: #f9fafb; }}
          .staff-heading td {{ background: #f0fdfa !important; }}
          .kpi-table {{ border: none; margin-bottom: 0; }}
          .kpi-table td {{ border: none; background: #f9fafb; border-radius: 6px;
                           padding: 10px 14px; text-align: center; width: 25%; }}
          .kpi-num   {{ font-size: 20px; font-weight: 700; color: #111827; }}
          .kpi-lbl   {{ font-size: 8.5px; color: #6b7280; margin-top: 2px; }}
        </style>
        </head>
        <body>
          <div class='header'>
            <div class='header-left'>
              <h1>Opsra</h1>
              <p>{org_name}</p>
              <p>Staff Activity Log — {date_from} to {date_to}</p>
              <p style='color:#9ca3af;font-size:9px'>Filter: {filter_label}</p>
            </div>
            <div class='header-right'>
              Generated: {gen_at[:10] if gen_at else ""}<br>
              By: {gen_by}
            </div>
          </div>
          {sections_html}
        </body>
        </html>
        """

        return _HTML(string=html).write_pdf()

    except Exception as exc:
        logger.error("_generate_activity_log_pdf failed: %s", exc)
        error_html = f"""
        <!DOCTYPE html><html><body>
        <p style='font-family:Arial;color:#dc2626;padding:40px'>
          Report generation failed: {exc}
        </p>
        </body></html>
        """
        from weasyprint import HTML as _HTML2
        return _HTML2(string=error_html).write_pdf()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/activity-logs/report/download")
def download_activity_log_report(
    date_from:           Optional[str] = None,
    date_to:             Optional[str] = None,
    user_id_filter:      Optional[str] = None,
    team:                Optional[str] = None,
    include_contractors: bool = True,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-2: Generate and download Staff Activity Log report as PDF.
    Filterable by date range, user, team.
    owner/ops_manager: can download for any user or all users.
    sales_agent: always filtered to own logs (Pattern 12).
    support_agent: 403.
    Rate limited: 10/hr via Redis. Fail open (S14).
    """
    role = (org.get("roles") or {}).get("template", "").lower()

    if role == "support_agent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Access denied"},
        )

    org_id          = org["org_id"]
    current_user_id = org["id"]
    is_manager      = role in ("owner", "ops_manager")

    if not _check_activity_log_report_rate_limit(org_id):
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

    # Pattern 12: sales_agent always sees only own logs regardless of query param
    if not is_manager:
        user_id_filter = current_user_id

    # Fetch logs
    query = (
        db.table("activity_logs")
        .select("*, user:user_id(id, full_name, team)")
        .eq("org_id", org_id)
        .gte("log_date", date_from)
        .lte("log_date", date_to)
        .order("log_date", desc=True)
    )
    if user_id_filter:
        query = query.eq("user_id", user_id_filter)
    elif team:
        query = query.eq("team", team)

    result = query.execute()
    logs = result.data or []
    if isinstance(logs, dict):
        logs = [logs]

    # Fetch org name
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

    # Fetch generating user's name
    user_result = (
        db.table("users")
        .select("full_name")
        .eq("id", current_user_id)
        .maybe_single()
        .execute()
    )
    user_row = user_result.data
    if isinstance(user_row, list):
        user_row = user_row[0] if user_row else {}
    gen_by = (user_row or {}).get("full_name") or ""

    # Build filter label
    if user_id_filter and user_id_filter != current_user_id:
        # try to get name from fetched logs
        match = next((l for l in logs if l.get("user_id") == user_id_filter), None)
        _fn = ((match or {}).get("user") or {}).get("full_name") if match else None
        filter_label = _fn or "Single staff member"
    elif not is_manager:
        filter_label = gen_by or "Own logs"
    elif team:
        filter_label = f"Team: {team}"
    else:
        filter_label = "All staff"

    # ── Python-side aggregations (Pattern 33) ─────────────────────────────────

    # Expand entries JSONB → individual rows; fall back to plain text blob
    log_rows = []
    blocker_rows = []
    staff_map: dict = {}

    for log in logs:
        user_obj  = log.get("user") or {}
        full_name = user_obj.get("full_name") or log.get("team") or "Unknown"
        _team     = user_obj.get("team") or log.get("team") or ""
        uid       = log.get("user_id") or ""
        log_date  = log.get("log_date") or ""

        if uid not in staff_map:
            staff_map[uid] = {
                "full_name": full_name,
                "team":      _team,
                "days":      set(),
                "activities": 0,
                "hours":      0,
                "blockers":   0,
            }
        staff_map[uid]["days"].add(log_date)

        entries = log.get("entries")
        if entries and isinstance(entries, list):
            for entry in entries:
                _hrs = entry.get("duration_minutes") or 0
                _has_blocker = entry.get("has_blocker", False)
                _blocker_note = entry.get("blocker_note") or ""

                log_rows.append({
                    "full_name":            full_name,
                    "team":                 _team,
                    "log_date":             log_date,
                    "activity_type":        entry.get("activity_type") or "General",
                    "activity_description": entry.get("activity_description") or "",
                    "duration_minutes":     _hrs if _hrs else None,
                    "has_blocker":          _has_blocker,
                    "blocker_note":         _blocker_note,
                })
                staff_map[uid]["activities"] += 1
                staff_map[uid]["hours"]      += _hrs or 0
                if _has_blocker:
                    staff_map[uid]["blockers"] += 1
                    blocker_rows.append({
                        "full_name":   full_name,
                        "log_date":    log_date,
                        "blocker_note": _blocker_note or "No details provided",
                    })
        else:
            # Legacy plain-text fallback
            _activities_text = log.get("activities") or ""
            _blockers_text   = log.get("blockers") or ""
            log_rows.append({
                "full_name":            full_name,
                "team":                 _team,
                "log_date":             log_date,
                "activity_type":        "General",
                "activity_description": _activities_text,
                "duration_minutes":     None,
                "has_blocker":          bool(_blockers_text),
                "blocker_note":         _blockers_text,
            })
            staff_map[uid]["activities"] += 1
            if _blockers_text:
                staff_map[uid]["blockers"] += 1
                blocker_rows.append({
                    "full_name":    full_name,
                    "log_date":     log_date,
                    "blocker_note": _blockers_text,
                })

    # Sort log_rows: by staff name asc, then date desc
    log_rows.sort(key=lambda r: (r.get("full_name") or "", r.get("log_date") or ""), reverse=False)
    log_rows.sort(key=lambda r: r.get("log_date") or "", reverse=True)
    # Re-sort so staff groups stay together, date desc within each group
    from itertools import groupby as _groupby
    grouped = []
    # Sort by name first to group, then within each group sort by date desc
    log_rows_sorted = sorted(log_rows, key=lambda r: (r.get("full_name") or ""))
    for _name, _entries in _groupby(log_rows_sorted, key=lambda r: r.get("full_name") or ""):
        grouped.extend(sorted(list(_entries), key=lambda r: r.get("log_date") or "", reverse=True))
    log_rows = grouped

    # Blocker rows sorted date desc
    blocker_rows.sort(key=lambda r: r.get("log_date") or "", reverse=True)

    # Per-staff summary list
    per_staff = []
    for uid, s in staff_map.items():
        per_staff.append({
            "full_name":   s["full_name"],
            "team":        s["team"],
            "days_logged": len(s["days"]),
            "activities":  s["activities"],
            "hours":       s["hours"],
            "blockers":    s["blockers"],
        })
    per_staff.sort(key=lambda x: (x.get("team") or "", x.get("full_name") or ""))

    total_activities = sum(s["activities"] for s in staff_map.values())
    total_hours      = sum(s["hours"]      for s in staff_map.values())
    total_blockers   = sum(s["blockers"]   for s in staff_map.values())
    staff_active     = len(staff_map)

    # ── Contractor activity logs (Pattern 33) ─────────────────────────────────
    contractor_rows        = []
    contractor_blocker_rows = []
    contractor_count       = 0

    if is_manager and include_contractors:
        # Fetch all active contractors for org
        contractors_result = (
            db.table("contractors")
            .select("id, full_name, role_title")
            .eq("org_id", org_id)
            .is_("deleted_at", "null")
            .execute()
        )
        contractors_list = contractors_result.data or []
        if isinstance(contractors_list, dict):
            contractors_list = [contractors_list]

        # Build id→name/role lookup
        contractor_lookup = {
            c["id"]: {"name": c.get("full_name") or "Unknown", "role": c.get("role_title") or ""}
            for c in contractors_list
        }

        if contractor_lookup:
            # Fetch contractor activity logs in date range
            contr_logs_result = (
                db.table("performance_daily_logs")
                .select(
                    "id, entity_id, log_date, kpi_label, notes, duration_minutes, "
                    "needs_management_attention, blocker_note, resolved_at, created_at"
                )
                .eq("org_id", org_id)
                .eq("kpi_key", "daily_activity")
                .gte("log_date", date_from)
                .lte("log_date", date_to)
                .order("log_date", desc=True)
                .order("created_at", desc=True)
                .execute()
            )
            contr_logs = contr_logs_result.data or []
            if isinstance(contr_logs, dict):
                contr_logs = [contr_logs]

            active_contractor_ids = set()
            for log in contr_logs:
                cid   = log.get("entity_id") or ""
                cinfo = contractor_lookup.get(cid, {})
                cname = cinfo.get("name") or "Unknown"
                crole = cinfo.get("role") or ""
                _has_blocker  = bool(log.get("needs_management_attention"))
                _blocker_note = (log.get("blocker_note") or "").strip()
                _resolved_at  = log.get("resolved_at")

                contractor_rows.append({
                    "contractor_name": cname,
                    "contractor_role": crole,
                    "log_date":        log.get("log_date") or "",
                    "activity_type":   (log.get("kpi_label") or "General").strip(),
                    "activity_description": (log.get("notes") or "").strip(),
                    "duration_minutes": log.get("duration_minutes"),
                    "has_blocker":      _has_blocker,
                    "blocker_note":     _blocker_note,
                    "resolved_at":      _resolved_at,
                })
                active_contractor_ids.add(cid)

                if _has_blocker:
                    contractor_blocker_rows.append({
                        "contractor_name": cname,
                        "log_date":        log.get("log_date") or "",
                        "blocker_note":    _blocker_note or "No details provided",
                        "resolved_at":     _resolved_at,
                    })

            # Sort contractor rows: by name asc, then date desc within each
            from itertools import groupby as _igroupby
            sorted_by_name = sorted(contractor_rows, key=lambda r: r.get("contractor_name") or "")
            grouped_contr  = []
            for _cn, _entries in _igroupby(sorted_by_name, key=lambda r: r.get("contractor_name") or ""):
                grouped_contr.extend(
                    sorted(list(_entries), key=lambda r: r.get("log_date") or "", reverse=True)
                )
            contractor_rows = grouped_contr

            # Blocker rows sorted date desc
            contractor_blocker_rows.sort(key=lambda r: r.get("log_date") or "", reverse=True)
            contractor_count = len(active_contractor_ids)

    report_data = {
        "meta": {
            "org_name":     org_name,
            "date_from":    date_from,
            "date_to":      date_to,
            "generated_at": now.isoformat(),
            "generated_by": gen_by,
            "filter_label": filter_label,
        },
        "summary": {
            "total_activities": total_activities,
            "total_hours":      total_hours,
            "total_blockers":   total_blockers,
            "staff_active":     staff_active,
            "contractor_count": contractor_count,
        },
        "per_staff":             per_staff,
        "log_rows":              log_rows,
        "blocker_rows":          blocker_rows,
        "contractor_rows":       contractor_rows,
        "contractor_blocker_rows": contractor_blocker_rows,
        "include_contractors":   is_manager and include_contractors,
        "is_manager":            is_manager,
    }

    pdf_bytes = _generate_activity_log_pdf(report_data)
    org_slug  = org_name.replace(" ", "_")
    filename  = f"Activity_Log_{org_slug}_{date_from}_to_{date_to}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/activity-logs/summary")
def get_activity_logs_summary(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Weekly summary — lists all team members and their log activity
    for the current week. Owner/ops_manager only.
    """
    if not _is_manager(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Manager access required"},
        )

    org_id = org["org_id"]
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    week_end = (today + timedelta(days=6 - today.weekday())).isoformat()

    # Fetch all active users in the org with their team
    users_result = (
        db.table("users")
        .select("id, full_name, team")
        .eq("org_id", org_id)
        .eq("is_active", True)
        .execute()
    )
    users = users_result.data or []
    if isinstance(users, dict):
        users = [users]

    # Fetch logs for this week
    logs_result = (
        db.table("activity_logs")
        .select("user_id, log_date, log_type")
        .eq("org_id", org_id)
        .gte("log_date", week_start)
        .lte("log_date", week_end)
        .execute()
    )
    logs = logs_result.data or []
    if isinstance(logs, dict):
        logs = [logs]

    # Build a lookup: user_id → { daily_count, has_weekly, latest_date }
    log_map: dict = {}
    for log in logs:
        uid = log["user_id"]
        if uid not in log_map:
            log_map[uid] = {"daily_count": 0, "has_weekly": False, "latest_date": None}
        if log["log_type"] == "weekly":
            log_map[uid]["has_weekly"] = True
        else:
            log_map[uid]["daily_count"] += 1
        ld = log["log_date"]
        if not log_map[uid]["latest_date"] or ld > log_map[uid]["latest_date"]:
            log_map[uid]["latest_date"] = ld

    members = []
    for u in users:
        uid = u["id"]
        entry = log_map.get(uid, {})
        members.append({
            "user_id":        uid,
            "full_name":      u.get("full_name", ""),
            "team":           u.get("team") or "",
            "logs_this_week": entry.get("daily_count", 0),
            "has_weekly_log": entry.get("has_weekly", False),
            "latest_log_date": entry.get("latest_date"),
        })

    return ok(data={"week_start": week_start, "members": members})


@router.post("/activity-logs")
def submit_activity_log(
    payload: ActivityLogCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Submit a daily or weekly log.
    Upserts on (org_id, user_id, log_date, log_type) unique key.
    user_id and team are always set from current user — never from payload.
    For weekly logs, log_date is normalised to the Monday of that week.
    """
    org_id = org["org_id"]
    user_id = org["id"]
    user_team = org.get("team") or ""

    if not payload.activities.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Activities field is required"},
        )

    # Normalise weekly log_date to Monday of that week
    log_date = payload.log_date
    if payload.log_type == "weekly":
        log_date = _week_start(log_date)

    now = datetime.now(timezone.utc).isoformat()

    # Check for existing log (upsert logic)
    existing = (
        db.table("activity_logs")
        .select("id")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .eq("log_date", log_date)
        .eq("log_type", payload.log_type)
        .maybe_single()
        .execute()
    )
    existing_data = existing.data
    if isinstance(existing_data, list):
        existing_data = existing_data[0] if existing_data else None

    update_fields = {
        "activities": payload.activities.strip(),
        "blockers":   payload.blockers or None,
        "plan":       payload.plan or None,
        "updated_at": now,
    }

    if existing_data:
        result = (
            db.table("activity_logs")
            .update(update_fields)
            .eq("id", existing_data["id"])
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else update_fields
        return ok(data=data, message="Activity log updated")
    else:
        row = {
            "org_id":     org_id,
            "user_id":    user_id,
            "log_date":   log_date,
            "log_type":   payload.log_type,
            "team":       user_team,
            "created_at": now,
            **update_fields,
        }
        result = db.table("activity_logs").insert(row).execute()
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else row
        return ok(data=data, message="Activity log submitted")

@router.post("/activity-logs/bulk")
def submit_activity_log_bulk(
    payload: ActivityLogBulkCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Submit multiple activity entries for a single day/week.
    Upserts on (org_id, user_id, log_date, log_type).
    Stores structured entries in the `entries` JSONB column.
    Generates a plain-text summary in `activities` for backwards compatibility.
    """
    org_id    = org["org_id"]
    user_id   = org["id"]
    user_team = org.get("team") or ""

    if not payload.entries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "At least one activity entry is required"},
        )

    valid_entries = [e for e in payload.entries if e.activity_description.strip()]
    if not valid_entries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "At least one activity description is required"},
        )

    log_date = payload.log_date
    if payload.log_type == "weekly":
        log_date = _week_start(log_date)

    # Build plain-text summary for backwards compatibility
    activities_text = "\n".join(
        f"[{e.activity_type}] {e.activity_description.strip()}"
        + (f" ({e.duration_minutes}h)" if e.duration_minutes else "")
        for e in valid_entries
    )
    blockers_text = "\n".join(
        e.blocker_note for e in valid_entries
        if e.has_blocker and e.blocker_note
    ) or None
    plan_text = next(
        (e.plan for e in reversed(valid_entries) if e.plan and e.plan.strip()),
        None
    )

    entries_json = [
        {
            "activity_description": e.activity_description.strip(),
            "activity_type":        e.activity_type,
            "duration_minutes":     e.duration_minutes,
            "has_blocker":          e.has_blocker,
            "blocker_note":         e.blocker_note if e.has_blocker else None,
            "plan":                 e.plan or None,
        }
        for e in valid_entries
    ]

    now = datetime.now(timezone.utc).isoformat()

    existing = (
        db.table("activity_logs")
        .select("id")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .eq("log_date", log_date)
        .eq("log_type", payload.log_type)
        .limit(1)
        .execute()
    )
    rows = existing.data or []
    if isinstance(rows, dict):
        rows = [rows]
    existing_data = rows[0] if rows else None

    update_fields = {
        "activities": activities_text,
        "blockers":   blockers_text,
        "plan":       plan_text,
        "entries":    entries_json,
        "updated_at": now,
    }

    # Auto-create issues for any blocker entries — S14: one failure never stops the loop
    def _maybe_create_blocker_issues(entries_json: list) -> list:
        """
        For each entry with has_blocker=True and no existing blocker_issue_id,
        create an internal issue and store the issue id back on the entry.
        Returns the updated entries list.
        """
        updated = []
        for entry in entries_json:
            if entry.get("has_blocker") and not entry.get("blocker_issue_id"):
                try:
                    ref = _generate_reference(db, org_id)
                    blocker_title = f"Blocker: {entry['activity_description'][:80]}"
                    blocker_desc  = entry.get("blocker_note") or "No details provided."
                    issue_row = {
                        "org_id":      org_id,
                        "reference":   ref,
                        "title":       blocker_title,
                        "description": blocker_desc,
                        "team":        user_team or "General",
                        "category":    "resource_blocker",
                        "priority":    "high",
                        "status":      "open",
                        "reported_by": user_id,
                        "assigned_to": None,
                        "created_at":  now,
                        "updated_at":  now,
                    }
                    issue_result = db.table("internal_issues").insert(issue_row).execute()
                    issue_data = issue_result.data
                    if isinstance(issue_data, list):
                        issue_data = issue_data[0] if issue_data else {}
                    issue_id = (issue_data or {}).get("id")
                    if issue_id:
                        entry = {**entry, "blocker_issue_id": issue_id}
                except Exception as exc:
                    logger.warning("_maybe_create_blocker_issues: failed for entry — %s", exc)
            updated.append(entry)
        return updated

    entries_json = _maybe_create_blocker_issues(entries_json)
    # Rebuild update_fields with potentially enriched entries
    update_fields["entries"] = entries_json

    if existing_data:
        result = (
            db.table("activity_logs")
            .update(update_fields)
            .eq("id", existing_data["id"])
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else update_fields
        return ok(data=data, message="Activity log updated")
    else:
        row = {
            "org_id":     org_id,
            "user_id":    user_id,
            "log_date":   log_date,
            "log_type":   payload.log_type,
            "team":       user_team,
            "created_at": now,
            **update_fields,
        }
        result = db.table("activity_logs").insert(row).execute()
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else row
        return ok(data=data, message="Activity log submitted")


@router.get("/activity-logs")
def list_activity_logs(
    user_id_filter: Optional[str] = None,
    team: Optional[str] = None,
    log_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: List activity logs.
    Non-managers see only their own logs.
    Managers can filter by user_id or team.
    """
    org_id = org["org_id"]
    current_user_id = org["id"]
    manager = _is_manager(org)

    query = (
        db.table("activity_logs")
        .select("*, user:user_id(id, full_name, team)")
        .eq("org_id", org_id)
        .order("log_date", desc=True)
    )

    if not manager:
        # Non-managers always see only their own logs
        query = query.eq("user_id", current_user_id)
    elif user_id_filter:
        query = query.eq("user_id", user_id_filter)
    elif team:
        query = query.eq("team", team)

    if log_type:
        query = query.eq("log_type", log_type)
    if date_from:
        query = query.gte("log_date", date_from)
    if date_to:
        query = query.lte("log_date", date_to)

    result = query.execute()
    logs = result.data or []
    if isinstance(logs, dict):
        logs = [logs]

    return ok(data={"items": logs, "total": len(logs)})


@router.patch("/activity-logs/{log_id}")
def update_activity_log(
    log_id: str,
    payload: ActivityLogUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Edit an activity log.
    Users can only edit their own logs.
    """
    org_id = org["org_id"]
    user_id = org["id"]

    existing = (
        db.table("activity_logs")
        .select("*")
        .eq("id", log_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    log_data = existing.data
    if isinstance(log_data, list):
        log_data = log_data[0] if log_data else None

    if not log_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Activity log not found"},
        )

    # Only the owner of the log can edit it
    if log_data.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "You can only edit your own activity logs"},
        )

    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "No fields provided to update"},
        )

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        db.table("activity_logs")
        .update(update_data)
        .eq("id", log_id)
        .eq("org_id", org_id)
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else update_data

    return ok(data=data, message="Activity log updated")
