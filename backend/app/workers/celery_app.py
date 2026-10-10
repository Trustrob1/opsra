"""
app/workers/celery_app.py
--------------------------
Celery application initialisation for Opsra background jobs.

Broker:  Upstash Redis via REDIS_URL (must use rediss:// TLS — Section 2.2)
Backend: Same Upstash Redis connection.

All scheduled jobs are defined here per Technical Spec Section 7.
Times are UTC — WAT (UTC+1) times from the spec are converted below:
    WAT 06:00 → UTC 05:00
    WAT 07:00 → UTC 06:00
    WAT 08:00 → UTC 07:00
    WAT 09:00 → UTC 08:00
    WAT 12:00 → UTC 11:00
    WAT 17:00 → UTC 16:00

M01-4/M01-5 additions:
    qualification_worker added to include list.
    Two new beat entries:
      - review_window_sender  (every minute — auto-sends scheduled outbox rows)
      - qualification_fallback (every hour — re-engages stuck sessions)

M01-7 additions:
    demo_reminder_worker added to include list.
    New beat entry:
      - demo_reminder_check  (every 15 minutes — 24h/1h reminders + no-show detection)

M01-10b additions:
    daily_briefing_worker added to include list.
    Three new beat entries:
      - daily_briefing        (06:00 WAT / 05:00 UTC — pre-generate morning briefings)
      - notification_digest_midday  (12:00 WAT / 11:00 UTC — bundle unread notifications)
      - notification_digest_eod     (17:00 WAT / 16:00 UTC — bundle unread notifications)

9E-A additions:
    Sentry SDK initialised with CeleryIntegration(monitor_beat_tasks=True).
    All scheduled beat tasks are automatically monitored via Sentry Crons.
    meta_token_worker added to include list.
    New beat entry:
      - meta_token_check (daily 07:00 WAT / 06:00 UTC — validate per-org Meta tokens)

SITE-3 part 2 additions:
    site_worker (already in the include list, SITE-1B §7.7) gains a second
    task, run_hosting_job_sla_check — spec §11.4 step 4 (amber at 12h before
    due, red + escalating alerts every 2h while overdue).
    New beat entry:
      - hosting-job-sla-check (every 15 minutes — mirrors sla_worker's own
        15-minute ticket-SLA cadence; the 4-hourly site-builder-timers entry
        below is too coarse for a 24h-SLA, 2h-escalation job)

SITE-3 leftover:
    site_worker gains run_approval_summary — spec §6.2 morning summary.
    New beat entry:
      - site-approval-summary (daily 07:00 UTC = 08:00 WAT)

SITE-4 part A:
    site_worker gains run_renewal_cycle — renewal reminders / lapse handling.
    New beat entry:
      - site-renewal-cycle (daily 06:30 UTC = 07:30 WAT)

SITE-4 part B:
    site_worker gains run_care_cycle and run_asset_cleanup. New beat entries:
      - site-care-cycle    (daily 06:45 UTC = 07:45 WAT)
      - site-asset-cleanup (daily 03:00 UTC = 04:00 WAT)
"""

import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_prerun, task_postrun
from kombu import Queue

from app.database import _active_clients, close_client_sessions


@task_prerun.connect
def _open_supabase_client_tracking(**kwargs):
    """
    OOM FIX (2026-07): opens a fresh tracking list at the start of every
    Celery task so get_supabase() calls made inside the task get registered
    for cleanup in task_postrun below.
    """
    _active_clients.set([])


@task_postrun.connect
def _close_supabase_client_tracking(**kwargs):
    """
    Closes every Supabase client's sessions created during this task.
    Same leak as the FastAPI request path — get_supabase() is called
    directly (not via Depends) in every worker file, and none of them
    close the client afterward.
    """
    for client in _active_clients.get() or []:
        close_client_sessions(client)

# ---------------------------------------------------------------------------
# Load REDIS_URL from the environment.
# In production this must be a rediss:// (TLS) URL from Upstash Redis.
# ---------------------------------------------------------------------------

REDIS_URL: str = os.environ.get("REDIS_URL", "")

if not REDIS_URL:
    raise RuntimeError(
        "REDIS_URL environment variable is not set. "
        "Set it to your Upstash Redis URL (rediss://...) before starting Celery."
    )

# Enforce TLS in production — plaintext redis:// is not permitted.
# Allow plain redis:// only when ENVIRONMENT=development to support local Redis.
ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "development")
if ENVIRONMENT == "production" and REDIS_URL.startswith("redis://"):
    raise RuntimeError(
        "REDIS_URL must use rediss:// (TLS) in production. "
        "Plaintext redis:// connections are not permitted."
    )

# Upstash Redis uses rediss:// (TLS). Celery requires ssl_cert_reqs to be
# explicitly set when using rediss://. Append it if not already present.
def _add_ssl_cert_reqs(url: str) -> str:
    if url.startswith("rediss://") and "ssl_cert_reqs" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}ssl_cert_reqs=CERT_NONE"
    return url

BROKER_URL  = _add_ssl_cert_reqs(REDIS_URL)
BACKEND_URL = _add_ssl_cert_reqs(REDIS_URL)

# ---------------------------------------------------------------------------
# Sentry — 9E-A Observability.
# monitor_beat_tasks=True automatically instruments every beat schedule entry
# as a Sentry Cron monitor — no per-task decoration required.
# SENTRY_DSN="" is safe (SDK becomes a no-op).
# ---------------------------------------------------------------------------
SENTRY_DSN: str = os.environ.get("SENTRY_DSN", "")

sentry_sdk.init(
    dsn=SENTRY_DSN,
    environment=ENVIRONMENT,
    integrations=[
        CeleryIntegration(monitor_beat_tasks=True),
    ],
    traces_sample_rate=0.2,
)

# ---------------------------------------------------------------------------
# Celery application — Technical Spec Section 7
# ---------------------------------------------------------------------------

celery_app = Celery(
    "opsra",
    broker=BROKER_URL,
    backend=BACKEND_URL,
    include=[
        # Worker modules — registered here so beat and workers can import them
        "app.workers.churn_worker",
        "app.workers.renewal_worker",
        "app.workers.nps_worker",
        "app.workers.digest_worker",
        "app.workers.sla_worker",
        "app.workers.drip_worker",
        "app.workers.qualification_worker",   # ← M01-4 + M01-5
        "app.workers.lead_sla_worker",        # ← M01-6
        "app.workers.demo_reminder_worker",   # ← M01-7
        "app.workers.lead_graduation_worker", # ← M01-10a
        "app.workers.lead_nurture_worker",    # ← M01-10a
        "app.workers.daily_briefing_worker",  # ← M01-10b
        "app.workers.growth_insights_worker", # ← GPM-2
        "app.workers.broadcast_worker",       # ← BROADCAST
        "app.workers.cart_abandonment_worker",# ← COMM-1
        "app.workers.meta_token_worker",      # ← 9E-A
        "app.workers.webhook_worker",      # ← 9E-B
        "app.workers.ai_resume_worker",    # ← AI-AUTO-RESUME
        "app.workers.instagram_worker",    # ← UNIFIED-INBOX-1A
        "app.workers.messenger_worker",    # ← UNIFIED-INBOX-1B
        "app.workers.report_delivery_worker",           # ← RPT-1A
        "app.workers.performance_retention_worker",     # ← CPM-1B
        "app.workers.performance_rollup_worker",        # ← CPM-1B Gap 1
        "app.workers.attribution_worker",               # ← ATTRIB-1
        "app.workers.health_score_worker",              # ← PERF-1C (registered now, worker built in PERF-1C)
        "app.workers.owner_report_worker",              # ← RPT-DAILY
        "app.workers.owner_pdf_worker",                  # ← OWNER-PDF-1
        "app.workers.funnel_worker",                     # ← FUNNEL-1A
        "app.workers.site_worker",                       # ← SITE-1B §7.7
        "app.workers.site_premium_worker",               # ← SITE-PREMIUM P2
        "app.workers.site_import_worker",                # ← SITE-IMPORT 2 (make an uploaded site editable)
    ],
)

# ---------------------------------------------------------------------------
# Celery configuration
# ---------------------------------------------------------------------------

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone — store internally in UTC; jobs are defined in UTC below
    timezone="UTC",
    enable_utc=True,
    # Result expiry — keep job results for 24 hours
    result_expires=86_400,
    # Routing — single default queue for Phase 1
    task_default_queue="default",
    # OUTAGE-FIX: never let a slow Redis hold a caller for minutes. Fail fast instead.
    broker_connection_timeout=5,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
        "retry_on_timeout": False,
        "max_retries": 1,
    },
    task_publish_retry=True,
    task_publish_retry_policy={"max_retries": 1, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5},
    task_queues=[
        Queue("default"),
    ],
    # Retry behaviour — prevent runaway retries
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_max_retries=3,
    # Worker concurrency — sensible default for Render's free tier
    worker_concurrency= 2,
    # Recycle each worker process after 50 tasks to prevent memory growth.
    # Each fork inherits the full parent memory; recycling caps accumulation.
    worker_max_tasks_per_child=50,
    worker_max_memory_per_child=200000,  # 200MB — recycle if a child exceeds this
    # Beat scheduler — file-based scheduler.
    # Schedule is stored in celerybeat-schedule file in the working directory.
    # NOTE: redbeat (Redis-backed) was trialled but could not be reliably
    # installed on Render. File-based scheduler remains in place until
    # redbeat deployment issue is resolved.
)

# ---------------------------------------------------------------------------
# Beat schedule — all jobs from Technical Spec Section 7 + M01-4/5/6/7/10b
#
# Crontab args:  minute, hour, day_of_week, day_of_month, month_of_year
# UTC hours used throughout (WAT - 1 hour).
#
# 9E-A: Sentry Cron monitors are applied automatically to every entry here
# via CeleryIntegration(monitor_beat_tasks=True) — no extra decoration needed.
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {

    # ------------------------------------------------------------------ #
    # daily_churn_scoring — Daily 06:00 WAT (05:00 UTC)                   #
    # Worker: churn_worker.py                                              #
    # ------------------------------------------------------------------ #
    "daily_churn_scoring": {
        "task": "app.workers.churn_worker.run_daily_churn_scoring",
        "schedule": crontab(hour=5, minute=0),
    },

    # ------------------------------------------------------------------ #
    # renewal_reminders — Daily 08:00 WAT (07:00 UTC)                     #
    # Worker: renewal_worker.py                                            #
    # ------------------------------------------------------------------ #
    "renewal_reminders": {
        "task": "app.workers.renewal_worker.run_renewal_reminders",
        "schedule": crontab(hour=7, minute=0),
    },

    # ------------------------------------------------------------------ #
    # monday_digest — Every Monday 07:00 WAT (06:00 UTC)                  #
    # Worker: digest_worker.py                                             #
    # ------------------------------------------------------------------ #
    "monday_digest": {
        "task": "app.workers.digest_worker.run_monday_digest",
        "schedule": crontab(hour=6, minute=0, day_of_week=1),  # 1 = Monday
    },

    # ------------------------------------------------------------------ #
    # nps_scheduler — Daily 09:00 WAT (08:00 UTC)                         #
    # Worker: nps_worker.py                                                #
    # ------------------------------------------------------------------ #
    "nps_scheduler": {
        "task": "app.workers.nps_worker.run_nps_scheduler",
        "schedule": crontab(hour=8, minute=0),
    },

    # ------------------------------------------------------------------ #
    # trial_expiry_checker — Daily 06:00 WAT (05:00 UTC)                  #
    # Worker: renewal_worker.py                                            #
    # ------------------------------------------------------------------ #
    "trial_expiry_checker": {
        "task": "app.workers.renewal_worker.run_trial_expiry_checker",
        "schedule": crontab(hour=5, minute=0),
    },

    # ------------------------------------------------------------------ #
    # sla_monitor — Every 15 minutes                                       #
    # Worker: sla_worker.py                                                #
    # ------------------------------------------------------------------ #
    "sla_monitor": {
        "task": "app.workers.sla_worker.run_sla_monitor",
        "schedule": crontab(minute="*/15"),
    },

    # ------------------------------------------------------------------ #
    # drip_scheduler — Daily 08:00 WAT (07:00 UTC)                        #
    # Worker: drip_worker.py                                               #
    # ------------------------------------------------------------------ #
    "drip_scheduler": {
        "task": "app.workers.drip_worker.run_drip_scheduler",
        "schedule": crontab(hour=7, minute=0),
    },

    # ------------------------------------------------------------------ #
    # win_back_scheduler — Daily 09:00 WAT (08:00 UTC)                    #
    # Worker: renewal_worker.py                                            #
    # ------------------------------------------------------------------ #
    "win_back_scheduler": {
        "task": "app.workers.renewal_worker.run_win_back_scheduler",
        "schedule": crontab(hour=8, minute=0),
    },

    # ------------------------------------------------------------------ #
    # lead_aging_checker — Daily 08:00 WAT (07:00 UTC)                    #
    # Worker: churn_worker.py                                              #
    # ------------------------------------------------------------------ #
    "lead_aging_checker": {
        "task": "app.workers.churn_worker.run_lead_aging_checker",
        "schedule": crontab(hour=7, minute=0),
    },

    # ------------------------------------------------------------------ #
    # anomaly_detector — Daily 06:00 WAT (05:00 UTC)                      #
    # Worker: churn_worker.py                                              #
    # ------------------------------------------------------------------ #
    "anomaly_detector": {
        "task": "app.workers.churn_worker.run_anomaly_detector",
        "schedule": crontab(hour=5, minute=0),
    },

    # ------------------------------------------------------------------ #
    # payment_failure_monitor — Every hour                                 #
    # Worker: renewal_worker.py                                            #
    # ------------------------------------------------------------------ #
    "payment_failure_monitor": {
        "task": "app.workers.renewal_worker.run_payment_failure_monitor",
        "schedule": crontab(minute=0),  # every hour at :00
    },

    # ------------------------------------------------------------------ #
    # re_engagement_queue — Daily 08:00 WAT (07:00 UTC)                   #
    # Worker: churn_worker.py                                              #
    # ------------------------------------------------------------------ #
    "re_engagement_queue": {
        "task": "app.workers.churn_worker.run_re_engagement_queue",
        "schedule": crontab(hour=7, minute=0),
    },

    # ------------------------------------------------------------------ #
    # review_window_sender — Every minute  (M01-4)                        #
    # Worker: qualification_worker.py                                      #
    # ------------------------------------------------------------------ #
    "review_window_sender": {
        "task": "app.workers.qualification_worker.run_review_window_sender",
        "schedule": crontab(minute="*/3"),  # every minute
    },

    # ------------------------------------------------------------------ #
    # qualification_fallback — Every hour  (M01-5)                        #
    # Worker: qualification_worker.py                                      #
    # ------------------------------------------------------------------ #
    "qualification_fallback": {
        "task": "app.workers.qualification_worker.run_qualification_fallback",
        "schedule": crontab(minute=0),  # every hour at :00
    },

    # ------------------------------------------------------------------ #
    # lead_sla_check — Every 2 minutes  (M01-6)                          #
    # Worker: lead_sla_worker.py                                           #
    # ------------------------------------------------------------------ #
    "lead_sla_check": {
        "task": "app.workers.lead_sla_worker.run_lead_sla_check",
        "schedule": crontab(minute="*/5"),
    },

    # ------------------------------------------------------------------ #
    # demo_reminder_check — Every 15 minutes  (M01-7)                     #
    # Worker: demo_reminder_worker.py                                      #
    # ------------------------------------------------------------------ #
    "demo_reminder_check": {
        "task": "app.workers.demo_reminder_worker.run_demo_reminder_check",
        "schedule": crontab(minute="*/15"),
    },

    # ------------------------------------------------------------------ #
    # lead_graduation_check — Daily 06:00 WAT (05:00 UTC)  (M01-10a)     #
    # Worker: lead_graduation_worker.py                                    #
    # ------------------------------------------------------------------ #
    "lead_graduation_check": {
        "task": "app.workers.lead_graduation_worker.run_lead_graduation_check",
        "schedule": crontab(hour=5, minute=0),
    },

    # ------------------------------------------------------------------ #
    # lead_nurture_send — Daily 08:00 WAT (07:00 UTC)  (M01-10a)         #
    # Worker: lead_nurture_worker.py                                       #
    # ------------------------------------------------------------------ #
    "lead_nurture_send": {
        "task": "app.workers.lead_nurture_worker.run_lead_nurture_send",
        "schedule": crontab(hour=7, minute=0),
    },

    # ------------------------------------------------------------------ #
    # daily_briefing — Daily 06:00 WAT (05:00 UTC)  (M01-10b)            #
    # Worker: daily_briefing_worker.py                                     #
    # Pre-generates Aria morning briefings for all active users.           #
    # ------------------------------------------------------------------ #
    "daily_briefing": {
        "task": "app.workers.daily_briefing_worker.run_daily_briefing_worker",
        "schedule": crontab(hour=5, minute=0),
    },

    # ------------------------------------------------------------------ #
    # notification_digest_midday — Daily 12:00 WAT (11:00 UTC)  (M01-10b)#
    # Worker: daily_briefing_worker.py                                     #
    # Bundles unread notifications into a natural-language Aria summary.  #
    # ------------------------------------------------------------------ #
    "notification_digest_midday": {
        "task": "app.workers.daily_briefing_worker.run_notification_digest",
        "schedule": crontab(hour=11, minute=0),
    },

    # ------------------------------------------------------------------ #
    # notification_digest_eod — Daily 17:00 WAT (16:00 UTC)  (M01-10b)  #
    # Worker: daily_briefing_worker.py                                     #
    # End-of-day notification bundle.                                      #
    # ------------------------------------------------------------------ #
    "notification_digest_eod": {
        "task": "app.workers.daily_briefing_worker.run_notification_digest",
        "schedule": crontab(hour=16, minute=0),
    },

    # ------------------------------------------------------------------ #
    # growth_anomaly_check — Daily 09:00 WAT (08:00 UTC)  (GPM-2)        #
    # Worker: growth_insights_worker.py                                   #
    # ------------------------------------------------------------------ #
    "growth_anomaly_check": {
       "task": "app.workers.growth_insights_worker.run_growth_anomaly_check",
       "schedule": crontab(hour=8, minute=0),
    },

    # ------------------------------------------------------------------ #
    # weekly_growth_digest — RETIRED (RPT-DAILY)                         #
    # Absorbed into owner_daily_report. On Mondays the weekly growth      #
    # section is appended to the daily brief message. Do not re-enable    #
    # without removing the Monday section from owner_report_worker.py.    #
    # ------------------------------------------------------------------ #
    # "weekly_growth_digest": {
    #    "task": "app.workers.growth_insights_worker.run_weekly_growth_digest",
    #    "schedule": crontab(hour=7, minute=0, day_of_week=1),
    # },

    # ------------------------------------------------------------------ #
    # owner_daily_report — Daily 07:30 WAT (06:30 UTC)  (RPT-DAILY)     #
    # Worker: owner_report_worker.py                                       #
    # Sends the org owner a WhatsApp brief with yesterday's KPIs + link   #
    # to the Owner Dashboard. On Mondays: weekly growth section appended. #
    # Slot: 30 min after monday_digest (06:00 UTC), before renewals       #
    # (07:00 UTC). D1 + D2 gates applied per org.                         #
    # ------------------------------------------------------------------ #
    "owner_daily_report": {
        "task": "app.workers.owner_report_worker.run_owner_daily_report",
        "schedule": crontab(hour=6, minute=30),
    },

    # ------------------------------------------------------------------ #
    # broadcast_dispatcher — Every 5 minutes  (BROADCAST)                 #
    # Worker: broadcast_worker.py                                          #
    # Dispatches scheduled and sending broadcasts to customers via Meta.   #
    # ------------------------------------------------------------------ #
    "broadcast_dispatcher": {
        "task": "app.workers.broadcast_worker.run_broadcast_dispatcher",
        "schedule": crontab(minute="*/10"),
    },

    # ------------------------------------------------------------------ #
    # cart_abandonment_check — Every 2 hours  (COMM-1)                   #
    # Worker: cart_abandonment_worker.py                                  #
    # Reminds contacts who received checkout link but never clicked it.   #
    # ------------------------------------------------------------------ #
    "cart-abandonment-check": {
        "task": "app.workers.cart_abandonment_worker.run_cart_abandonment_check",
        "schedule": crontab(minute=0, hour="*/2"),  # every 2h at :00
    },

    # ------------------------------------------------------------------ #
    # meta_token_check — Daily 07:00 WAT (06:00 UTC)  (9E-A)             #
    # Worker: meta_token_worker.py                                         #
    # Validates WhatsApp access token for every active org.               #
    # Invalid token → in-app notification to org owner.                   #
    # ------------------------------------------------------------------ #
    "meta_token_check": {
        "task": "app.workers.meta_token_worker.run_meta_token_check",
        "schedule": crontab(hour=6, minute=15),
    },

    # ------------------------------------------------------------------ #
    # purge_aria_messages — Daily 02:00 UTC  (9E-G)                       #
    # Worker: daily_briefing_worker.py                                     #
    # Deletes assistant_messages older than 30 days to cap table growth.  #
    # ------------------------------------------------------------------ #
    "purge_aria_messages": {
        "task": "app.workers.daily_briefing_worker.run_purge_old_messages",
        "schedule": crontab(hour=2, minute=0),
    },

    # ------------------------------------------------------------------ #
    # ai_auto_resume — Every 5 minutes  (AI-AUTO-RESUME)                  #
    # Worker: ai_resume_worker.py                                          #
    # Auto-resumes AI for contacts left in Human Mode > 15 min inactive.  #
    # ------------------------------------------------------------------ #
    "ai_auto_resume": {
        "task": "app.workers.ai_resume_worker.run_ai_auto_resume",
        "schedule": crontab(minute="*/5"),
    },

    # ------------------------------------------------------------------ #
    # run_report_delivery — Every 30 minutes  (RPT-1A)                    #
    # Worker: report_delivery_worker.py                                    #
    # Delivers scheduled management reports via email.                    #
    # ------------------------------------------------------------------ #
    "run-report-delivery": {
        "task": "run_report_delivery",
        "schedule": crontab(minute="*/30"),
    },

    # ------------------------------------------------------------------ #
    # rollup_daily_performance_logs — Daily 01:00 UTC  (CPM-1B Gap 1)    #
    # Worker: performance_rollup_worker.py                                #
    # Auto-promotes daily log totals to monthly KPI actuals at month end. #
    # Skips KPIs where an actual already exists (manager entry wins).     #
    # ------------------------------------------------------------------ #
    "rollup-daily-performance-logs": {
        "task": "rollup_daily_performance_logs",
        "schedule": crontab(hour=1, minute=0),
    },

    # ------------------------------------------------------------------ #
    # archive_old_performance_logs — 1st of each month, 02:00 UTC (CPM-1B)#
    # Worker: performance_retention_worker.py                              #
    # Deletes daily logs older than each contractor's retention setting.  #
    # ------------------------------------------------------------------ #
    "archive-performance-logs-monthly": {
        "task": "archive_old_performance_logs",
        "schedule": crontab(day_of_month=1, hour=2, minute=0),
    },

    # ------------------------------------------------------------------ #
    # attribution_auto_confirm — Every hour  (ATTRIB-1)                  #
    # Worker: attribution_worker.py                                       #
    # Auto-confirms attribution for leads where ops manager did not act   #
    # within 24 hours of the attribution_review_needed notification.      #
    # ------------------------------------------------------------------ #
    "attribution-auto-confirm": {
        "task": "app.workers.attribution_worker.run_attribution_auto_confirm",
        "schedule": crontab(minute=10),  # every hour at :00
    },

    # ------------------------------------------------------------------ #
    # health_score_recalc — Every 30 minutes  (PERF-1C)                  #
    # Worker: health_score_worker.py                                      #
    # Recalculates + caches org health scores for all active orgs.       #
    # Built in PERF-1C session — registered here now so beat is ready.  #
    # ------------------------------------------------------------------ #
    "health-score-recalc": {
        "task": "app.workers.health_score_worker.run_health_score_recalc",
        "schedule": crontab(minute=0),
    },

    # ------------------------------------------------------------------ #
    # funnel_sequence — Every 5 minutes  (FUNNEL-1A)                     #
    # Worker: funnel_worker.py                                            #
    # Event Funnel follow-ups + event reminders; stops on payment.       #
    # ------------------------------------------------------------------ #
    "funnel-sequence": {
        "task": "app.workers.funnel_worker.run_funnel_sequence",
        "schedule": crontab(minute="*/5"),
    },

    # ------------------------------------------------------------------ #
    # site-builder-timers — Every 4 hours  (SITE-1B §7.7)                #
    # Worker: site_worker.py                                              #
    # Brief/form reminders + form/preview expiry. Every 4h (not more     #
    # often) is the minimum cadence that still lands the 20h brief       #
    # reminder inside the 24h free-messaging window — coarser than that  #
    # risks missing it and forcing a paid template send instead. Costs   #
    # nothing extra either way: same worker dyno, no new Render service. #
    # ------------------------------------------------------------------ #
    "site-builder-timers": {
        "task": "app.workers.site_worker.run_site_builder_timers",
        "schedule": crontab(minute=0, hour="*/4"),
    },

    # ------------------------------------------------------------------ #
    # hosting-job-sla-check — Every 15 minutes  (SITE-3 part 2)          #
    # Worker: site_worker.py                                              #
    # Amber at 12h before due, red + escalating alerts every 2h overdue. #
    # ------------------------------------------------------------------ #
    "hosting-job-sla-check": {
        "task": "app.workers.site_worker.run_hosting_job_sla_check",
        "schedule": crontab(minute="*/15"),
    },

    # ------------------------------------------------------------------ #
    # site-approval-summary — Daily 07:00 UTC = 08:00 WAT  (SITE-3)      #
    # Worker: site_worker.py                                              #
    # Morning push + in-app summary of orders waiting for approval        #
    # (spec §6.2). Orders paid 23:00-08:00 wait for the approval window;  #
    # this tells Trust they are there. Silent when nothing is waiting.    #
    # ------------------------------------------------------------------ #
    "site-approval-summary": {
        "task": "app.workers.site_worker.run_approval_summary",
        "schedule": crontab(minute=0, hour=7),
    },

    # ------------------------------------------------------------------ #
    # site-renewal-cycle — Daily 06:30 UTC = 07:30 WAT  (SITE-4)         #
    # Worker: site_worker.py                                              #
    # Domain/site status, builder reminders at 30/14/7 days with a pay    #
    # link, client WhatsApp at <=5 days, one-off alert on lapse.          #
    # ------------------------------------------------------------------ #
    "site-renewal-cycle": {
        "task": "app.workers.site_worker.run_renewal_cycle",
        "schedule": crontab(minute=30, hour=6),
    },

    # ------------------------------------------------------------------ #
    # site-care-cycle — Daily 06:45 UTC = 07:45 WAT  (SITE-4B)           #
    # Care plans: active -> grace -> ended; one payment link per period.  #
    # ------------------------------------------------------------------ #
    "site-care-cycle": {
        "task": "app.workers.site_worker.run_care_cycle",
        "schedule": crontab(minute=45, hour=6),
    },

    # ------------------------------------------------------------------ #
    # site-addon-cycle — Daily 06:50 UTC = 07:50 WAT  (SITE-ADDONS A0-2)  #
    # Tiers / add-ons: active -> grace -> paused; renewal reminders to    #
    # the client (email, WhatsApp inside the 24h window).                 #
    # ------------------------------------------------------------------ #
    "site-addon-cycle": {
        "task": "app.workers.site_worker.run_addon_cycle",
        "schedule": crontab(minute=50, hour=6),
    },

    # ------------------------------------------------------------------ #
    # site-asset-cleanup — Daily 03:00 UTC = 04:00 WAT  (SITE-4B)        #
    # Deletes uploaded images 90 days after a site is cancelled or its   #
    # domain lapsed; warns managers 7 days before. Text is kept.         #
    # ------------------------------------------------------------------ #
    "site-giveaway-deadlines": {          # GIVEAWAY-2: hourly - remind unpaid giveaway winners, then release the slot
        "task": "app.workers.site_worker.run_giveaway_deadlines",
        "schedule": crontab(minute=20),
    },

    "site-asset-cleanup": {
        "task": "app.workers.site_worker.run_asset_cleanup",
        "schedule": crontab(minute=0, hour=3),
    },

    # ------------------------------------------------------------------ #
    # site-backup — Daily 01:00 UTC = 02:00 WAT  (SITE-BACKUP)           #
    # Copies every published site from R2 to the separate backup bucket,   #
    # verifies each copy, keeps the newest 14 snapshots per site and      #
    # writes a run record. Alerts managers when it fails.                 #
    # ------------------------------------------------------------------ #
    "site-backup": {
        "task": "app.workers.site_worker.run_site_backup",
        "schedule": crontab(minute=0, hour=1),
    },

    # ------------------------------------------------------------------ #
    # site-backup-watchdog — Daily 06:00 UTC = 07:00 WAT  (SITE-BACKUP)  #
    # Alerts when no backup started in 26h, or the last one failed.       #
    # ------------------------------------------------------------------ #
    "site-backup-watchdog": {
        "task": "app.workers.site_worker.run_site_backup_watchdog",
        "schedule": crontab(minute=0, hour=6),
    },

    # ------------------------------------------------------------------ #
    # site-premium-stale-sweep — every 10 minutes  (SITE-PREMIUM P2)      #
    # Marks a Premium generation stuck for 20+ minutes as failed, so the  #
    # site is never blocked by a worker that died.                        #
    # ------------------------------------------------------------------ #
    "site-premium-stale-sweep": {
        "task": "app.workers.site_premium_worker.run_premium_stale_sweep",
        "schedule": crontab(minute="*/10"),
    },
}

