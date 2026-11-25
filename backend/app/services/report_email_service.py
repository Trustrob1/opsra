"""
app/services/report_email_service.py
------------------------------------
REPORT-1 - reports emailed to the owner.

  daily_all(db, now)    every business with daily_sales_report on: yesterday's sales report (PDF + CSV)
  weekly_all(db, now)   every business with weekly_reports on: last Monday-Sunday's sales report, plus the inventory
                        report when stock is on
  send_daily(db, org_id, day) / send_weekly(db, org_id, week_end)   one business (also used by "Send now")

Who gets them: invoice_settings.report_emails, else the business's owner logins.
Each business is claimed with a conditional update of last_daily_report_on / last_weekly_report_on first, so a retried
or doubled beat never sends the same report twice. Never raises (S14); failures are logged.
"""
from __future__ import annotations

import html
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.services import business_report_service as biz
from app.services import invoice_service as inv
from app.utils.org_gates import is_org_active

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_RECIPIENTS = 10


def _rows(res) -> list:
    return (res.data or []) if res else []


def clean_emails(values) -> list:
    out = []
    for v in values or []:
        v = str(v or "").strip().lower()
        if v and EMAIL_RE.match(v) and v not in out:
            out.append(v)
    return out[:MAX_RECIPIENTS]


def recipients(db, org_id: str, settings: Optional[dict] = None) -> list:
    st = settings or inv.get_settings(db, org_id)
    to = clean_emails(st.get("report_emails"))
    if to:
        return to
    from app.services import stock_alert_service
    return clean_emails(stock_alert_service._owner_emails(db, org_id))


def lagos_today(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(inv.LAGOS).date()


def _money(v) -> str:
    return biz.pdf.money(v)


def _send(to: list, business: str, subject: str, lines: list, files: list) -> int:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key or not to:
        return 0
    sender = os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io")
    text = "\n".join(lines) + "\n\nThe full report is attached as a PDF, with a CSV you can open in a spreadsheet."
    body = ('<div style="font-family:Arial,sans-serif;font-size:14px;color:#222">'
            + "".join(f"<p style=\"margin:4px 0\">{html.escape(l)}</p>" for l in lines)
            + '<p style="color:#666;font-size:13px">The full report is attached as a PDF, with a CSV you can open '
              'in a spreadsheet.</p></div>')
    clean = re.sub(r"[^\w .&'-]", "", business or "")[:60].strip() or "Opsra"
    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({"from": f"{clean} reports <{sender}>", "to": to, "subject": subject[:200], "text": text,
                            "html": body,
                            "attachments": [{"filename": n, "content": list(d)} for n, d in files if d]})
        return len(to)
    except Exception as exc:
        logger.error("report_email: send failed subject=%s: %s", subject, exc)
        return 0


def _sales_files(data: dict, settings: dict) -> list:
    pdf_bytes, name = biz.sales_pdf(data, settings)
    return [(name, pdf_bytes), (biz.filename("sales", data, "csv"), biz.sales_csv(data).encode("utf-8-sig"))]


def _sales_lines(data: dict) -> list:
    t = data["totals"]
    lines = [f"Sales: {t['count']} worth {_money(t['value'])}",
             f"Money received: {_money(t['received'])} ({t['payments']} payment{'s' if t['payments'] != 1 else ''})",
             f"Still owed on these sales: {_money(t['owed'])}"]
    if data["by_rep"]:
        top = data["by_rep"][0]
        lines.append(f"Top rep: {top['name']} ({top['count']} sale{'s' if top['count'] != 1 else ''}, {_money(top['value'])})")
    return lines


def send_daily(db, org_id: str, day: date) -> int:
    st = inv.get_settings(db, org_id)
    to = recipients(db, org_id, st)
    if not to:
        return 0
    data = biz.sales_data(db, org_id, day, day)
    business = st.get("business_name") or "Your business"
    return _send(to, business, f"{business}: sales for {day.strftime('%a %d %b %Y')}",
                 [f"Sales report for {day.strftime('%A %d %B %Y')}.", ""] + _sales_lines(data), _sales_files(data, st))


def send_weekly(db, org_id: str, week_end: date) -> int:
    st = inv.get_settings(db, org_id)
    to = recipients(db, org_id, st)
    if not to:
        return 0
    start = week_end - timedelta(days=6)
    data = biz.sales_data(db, org_id, start, week_end)
    files = _sales_files(data, st)
    business = st.get("business_name") or "Your business"
    lines = [f"Weekly report for {start.strftime('%d %b')} to {week_end.strftime('%d %b %Y')}.", ""] + _sales_lines(data)
    try:
        from app.services import inventory_service as stock
        if stock.stock_on(db, org_id):
            inv_data = biz.inventory_data(db, org_id, start, week_end)
            inv_pdf, inv_name = biz.inventory_pdf(inv_data, st)
            files += [(inv_name, inv_pdf),
                      (biz.filename("inventory", inv_data, "csv"), biz.inventory_csv(inv_data).encode("utf-8-sig"))]
            s = inv_data["summary"]
            lines += ["", f"Stock: {s.get('units_on_hand', 0)} units on hand, worth {_money(s.get('stock_value', 0))} at cost",
                      f"Running low: {s.get('low', 0)} item{'s' if s.get('low', 0) != 1 else ''}",
                      f"Paid and waiting delivery: {len(inv_data['waiting'])} order{'s' if len(inv_data['waiting']) != 1 else ''}"]
    except Exception as exc:
        logger.error("report_email: inventory part failed org=%s: %s", org_id, exc)
    return _send(to, business, f"{business}: weekly report", lines, files)


def _claim(db, org_id: str, column: str, day: date) -> bool:
    """Mark this report as sent for `day` only if it wasn't already; True when this run won."""
    first = db.table("invoice_settings").update({column: str(day)}).eq("org_id", org_id).is_(column, "null").execute()
    if _rows(first):
        return True
    res = db.table("invoice_settings").update({column: str(day)}).eq("org_id", org_id).lt(column, str(day)).execute()
    return bool(_rows(res))


def _run(db, flag: str, column: str, day: date, send) -> dict:
    out = {"orgs": 0, "sent": 0, "failed": 0}
    rows = _rows(db.table("invoice_settings").select("org_id").eq(flag, True).execute())
    ids = [r["org_id"] for r in rows]
    active = {o["id"] for o in _rows(db.table("organisations").select("id, subscription_status").in_("id", ids).execute())
              if is_org_active(o)} if ids else set()
    for org_id in ids:
        if org_id not in active:   # D1: lapsed or suspended businesses get nothing
            continue
        try:
            if not _claim(db, org_id, column, day):
                continue
            out["orgs"] += 1
            if send(db, org_id, day):
                out["sent"] += 1
            else:
                out["failed"] += 1
        except Exception as exc:
            out["failed"] += 1
            logger.error("report_email: %s failed org=%s: %s", flag, org_id, exc)
    return out


def daily_all(db, now: Optional[datetime] = None) -> dict:
    return _run(db, "daily_sales_report", "last_daily_report_on", lagos_today(now) - timedelta(days=1), send_daily)


def weekly_all(db, now: Optional[datetime] = None) -> dict:
    today = lagos_today(now)
    last_sunday = today - timedelta(days=today.isoweekday() % 7 or 7)   # the Sunday before today (never today)
    return _run(db, "weekly_reports", "last_weekly_report_on", last_sunday, send_weekly)
