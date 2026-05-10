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
"""

import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

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
    task_queues=[
        Queue("default"),
    ],
    # Retry behaviour — prevent runaway retries
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_max_retries=3,
    # Worker concurrency — sensible default for Render's free tier
    worker_concurrency=4,
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
        "schedule": crontab(minute="*"),  # every minute
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
    # lead_sla_check — Every 15 minutes  (M01-6)                          #
    # Worker: lead_sla_worker.py                                           #
    # ------------------------------------------------------------------ #
    "lead_sla_check": {
        "task": "app.workers.lead_sla_worker.run_lead_sla_check",
        "schedule": crontab(minute="*/15"),
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
    # weekly_growth_digest — Every Monday 08:00 WAT (07:00 UTC)  (GPM-2) #
    # Worker: growth_insights_worker.py                                   #
    # ------------------------------------------------------------------ #
    "weekly_growth_digest": {
       "task": "app.workers.growth_insights_worker.run_weekly_growth_digest",
       "schedule": crontab(hour=7, minute=0, day_of_week=1),
    },

    # ------------------------------------------------------------------ #
    # broadcast_dispatcher — Every 5 minutes  (BROADCAST)                 #
    # Worker: broadcast_worker.py                                          #
    # Dispatches scheduled and sending broadcasts to customers via Meta.   #
    # ------------------------------------------------------------------ #
    "broadcast_dispatcher": {
        "task": "app.workers.broadcast_worker.run_broadcast_dispatcher",
        "schedule": crontab(minute="*/5"),
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
        "schedule": crontab(hour=6, minute=0),
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
}
