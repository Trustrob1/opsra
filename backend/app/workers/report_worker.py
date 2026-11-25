"""
app/workers/report_worker.py
----------------------------
REPORT-1.
  daily_sales_report   daily 07:00 WAT (06:00 UTC): yesterday's sales report to each business that turned it on
  weekly_reports       Mondays 07:05 WAT: last week's sales report, plus the inventory report when stock is on

Manual run:
  python -c "from dotenv import load_dotenv; load_dotenv(); from app.workers.report_worker import daily_sales_report; print(daily_sales_report())"
"""
from __future__ import annotations

from app.services import report_email_service
from app.workers.celery_app import celery_app
from app.workers.stock_worker import _run


@celery_app.task(name="app.workers.report_worker.daily_sales_report")
def daily_sales_report() -> dict:
    return _run("report_daily_sales", report_email_service.daily_all, lambda r: r["sent"])


@celery_app.task(name="app.workers.report_worker.weekly_reports")
def weekly_reports() -> dict:
    return _run("report_weekly", report_email_service.weekly_all, lambda r: r["sent"])
