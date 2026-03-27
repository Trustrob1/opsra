"""
app/workers/celery_app.py
--------------------------
Celery application initialisation for Opsra background jobs.

Broker:  Upstash Redis via REDIS_URL (must use rediss:// TLS — Section 2.2)
Backend: Same Upstash Redis connection.

All 12 scheduled jobs are defined here per Technical Spec Section 7.
Times are UTC — WAT (UTC+1) times from the spec are converted below:
    WAT 06:00 → UTC 05:00
    WAT 07:00 → UTC 06:00
    WAT 08:00 → UTC 07:00
    WAT 09:00 → UTC 08:00
"""

import os

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

# ---------------------------------------------------------------------------
# Celery application — Technical Spec Section 7
# ---------------------------------------------------------------------------

celery_app = Celery(
    "opsra",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        # Worker modules — registered here so beat and workers can import them
        "app.workers.churn_worker",
        "app.workers.renewal_worker",
        "app.workers.nps_worker",
        "app.workers.digest_worker",
        "app.workers.sla_worker",
        "app.workers.drip_worker",
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
    worker_concurrency=2,
    # Beat scheduler persistence — store schedule in Redis so restarts
    # do not re-fire all jobs immediately
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=REDIS_URL,
    redbeat_key_prefix="opsra:beat:",
)

# ---------------------------------------------------------------------------
# Beat schedule — all 12 jobs from Technical Spec Section 7
#
# Crontab args:  minute, hour, day_of_week, day_of_month, month_of_year
# UTC hours used throughout (WAT - 1 hour).
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {

    # ------------------------------------------------------------------ #
    # daily_churn_scoring — Daily 06:00 WAT (05:00 UTC)                   #
    # Worker: churn_worker.py                                              #
    # Calculates churn risk for every active customer, updates             #
    # churn_scores table and customers.churn_risk. Triggers alerts.        #
    # ------------------------------------------------------------------ #
    "daily_churn_scoring": {
        "task": "app.workers.churn_worker.run_daily_churn_scoring",
        "schedule": crontab(hour=5, minute=0),
    },

    # ------------------------------------------------------------------ #
    # renewal_reminders — Daily 08:00 WAT (07:00 UTC)                     #
    # Worker: renewal_worker.py                                            #
    # Sends WhatsApp renewal reminders at 60/30/14/7 day thresholds.      #
    # ------------------------------------------------------------------ #
    "renewal_reminders": {
        "task": "app.workers.renewal_worker.run_renewal_reminders",
        "schedule": crontab(hour=7, minute=0),
    },

    # ------------------------------------------------------------------ #
    # monday_digest — Every Monday 07:00 WAT (06:00 UTC)                  #
    # Worker: digest_worker.py                                             #
    # Generates personalised weekly digest via Claude Haiku, sends        #
    # WhatsApp message to each staff member.                               #
    # ------------------------------------------------------------------ #
    "monday_digest": {
        "task": "app.workers.digest_worker.run_monday_digest",
        "schedule": crontab(hour=6, minute=0, day_of_week=1),  # 1 = Monday
    },

    # ------------------------------------------------------------------ #
    # nps_scheduler — Daily 09:00 WAT (08:00 UTC)                         #
    # Worker: nps_worker.py                                                #
    # Checks quarterly NPS eligibility (90 days since last send).         #
    # Skips if event-triggered NPS sent within 14 days.                   #
    # ------------------------------------------------------------------ #
    "nps_scheduler": {
        "task": "app.workers.nps_worker.run_nps_scheduler",
        "schedule": crontab(hour=8, minute=0),
    },

    # ------------------------------------------------------------------ #
    # trial_expiry_checker — Daily 06:00 WAT (05:00 UTC)                  #
    # Worker: renewal_worker.py                                            #
    # Sends Day 3/7 conversion prompts. Initiates grace on expiry.        #
    # Suspends after 3-day grace period.                                   #
    # ------------------------------------------------------------------ #
    "trial_expiry_checker": {
        "task": "app.workers.renewal_worker.run_trial_expiry_checker",
        "schedule": crontab(hour=5, minute=0),
    },

    # ------------------------------------------------------------------ #
    # sla_monitor — Every 15 minutes                                       #
    # Worker: sla_worker.py                                                #
    # Checks open tickets for SLA compliance. Sends pre-breach alerts.    #
    # Marks sla_breached=true. Triggers escalation tasks.                  #
    # ------------------------------------------------------------------ #
    "sla_monitor": {
        "task": "app.workers.sla_worker.run_sla_monitor",
        "schedule": crontab(minute="*/15"),
    },

    # ------------------------------------------------------------------ #
    # drip_scheduler — Daily 08:00 WAT (07:00 UTC)                        #
    # Worker: drip_worker.py                                               #
    # Sends due drip messages unless paused. Updates drip_sends status.   #
    # ------------------------------------------------------------------ #
    "drip_scheduler": {
        "task": "app.workers.drip_worker.run_drip_scheduler",
        "schedule": crontab(hour=7, minute=0),
    },

    # ------------------------------------------------------------------ #
    # win_back_scheduler — Daily 09:00 WAT (08:00 UTC)                    #
    # Worker: renewal_worker.py                                            #
    # Checks churned customers at 14/30/60 day marks.                     #
    # Queues win-back messages for approval.                               #
    # ------------------------------------------------------------------ #
    "win_back_scheduler": {
        "task": "app.workers.renewal_worker.run_win_back_scheduler",
        "schedule": crontab(hour=8, minute=0),
    },

    # ------------------------------------------------------------------ #
    # lead_aging_checker — Daily 08:00 WAT (07:00 UTC)                    #
    # Worker: churn_worker.py                                              #
    # Flags leads with no activity for 3+ days. Creates re-engagement     #
    # task for the assigned rep.                                           #
    # ------------------------------------------------------------------ #
    "lead_aging_checker": {
        "task": "app.workers.churn_worker.run_lead_aging_checker",
        "schedule": crontab(hour=7, minute=0),
    },

    # ------------------------------------------------------------------ #
    # anomaly_detector — Daily 06:00 WAT (05:00 UTC)                      #
    # Worker: churn_worker.py                                              #
    # Compares current vs previous week metrics. Flags anomalies.         #
    # Creates alerts in notifications table.                               #
    # ------------------------------------------------------------------ #
    "anomaly_detector": {
        "task": "app.workers.churn_worker.run_anomaly_detector",
        "schedule": crontab(hour=5, minute=0),
    },

    # ------------------------------------------------------------------ #
    # payment_failure_monitor — Every hour                                 #
    # Worker: renewal_worker.py                                            #
    # Checks pending payments older than 24 hours.                        #
    # Sends customer WhatsApp notification. Begins grace period.          #
    # ------------------------------------------------------------------ #
    "payment_failure_monitor": {
        "task": "app.workers.renewal_worker.run_payment_failure_monitor",
        "schedule": crontab(minute=0),  # every hour at :00
    },

    # ------------------------------------------------------------------ #
    # re_engagement_queue — Daily 08:00 WAT (07:00 UTC)                   #
    # Worker: churn_worker.py                                              #
    # Checks leads where reengagement_date = today. Moves stage to new.  #
    # Creates task for assigned rep.                                       #
    # ------------------------------------------------------------------ #
    "re_engagement_queue": {
        "task": "app.workers.churn_worker.run_re_engagement_queue",
        "schedule": crontab(hour=7, minute=0),
    },
}