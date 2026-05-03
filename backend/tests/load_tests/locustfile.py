"""
Opsra Load Test — locustfile.py
================================
Runs with Locust against the staging backend URL.

Quick start:
  pip install locust
  set OPSRA_BACKEND_URL=https://opsra.onrender.com
  locust -f load_tests/locustfile.py --host=%OPSRA_BACKEND_URL%

See load_tests/README.md for full instructions and pass/fail criteria.
"""

import os
import random
import logging
from locust import HttpUser, task, between, events
from locust.exception import StopUser

from tests.load_tests.test_data import (
    STAFF_ACCOUNTS,
    MANAGER_ACCOUNTS,
    STAGING_ORG_SLUG,
    THRESHOLD_STANDARD_MS,
    THRESHOLD_AI_MS,
    THRESHOLD_SEARCH_MS,
    THRESHOLD_DASHBOARD_MS,
    lead_create_payload,
    ticket_create_payload,
    task_create_payload,
    ask_payload,
    lead_form_public_payload,
    STANDARD_GET_ENDPOINTS,
    SEARCH_ENDPOINTS,
)

log = logging.getLogger("opsra-load")

# ---------------------------------------------------------------------------
# Threshold violation tracker — aggregated and printed at test end
# ---------------------------------------------------------------------------
_threshold_violations: list[dict] = []


def _check_threshold(response, name: str, threshold_ms: int):
    """Log a violation if response time exceeds the DRD threshold."""
    elapsed = response.elapsed.total_seconds() * 1000
    if elapsed > threshold_ms:
        _threshold_violations.append({
            "endpoint": name,
            "elapsed_ms": round(elapsed),
            "threshold_ms": threshold_ms,
        })
        log.warning(
            "THRESHOLD BREACH — %s: %.0fms > %dms limit",
            name, elapsed, threshold_ms
        )


@events.quitting.add_listener
def _print_threshold_report(environment, **kwargs):
    if not _threshold_violations:
        print("\n✅  No threshold violations detected.")
        return
    print(f"\n⚠️  {len(_threshold_violations)} threshold violation(s):")
    for v in _threshold_violations:
        print(f"   {v['endpoint']}: {v['elapsed_ms']}ms  (limit {v['threshold_ms']}ms)")


# ---------------------------------------------------------------------------
# Base user — handles login and token refresh
# ---------------------------------------------------------------------------
class OpsraBaseUser(HttpUser):
    """
    Logs in with a rotating staff credential from STAFF_ACCOUNTS.
    Subclasses use self.auth_headers to make authenticated requests.
    Simulates one of the 10 staff members working simultaneously.
    """
    abstract = True
    wait_time = between(1, 5)   # realistic think time between actions

    def on_start(self):
        account = random.choice(STAFF_ACCOUNTS)
        self._login(account["email"], account["password"], account["label"])

    def _login(self, email: str, password: str, label: str):
        with self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            catch_response=True,
            name="POST /auth/login",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Login failed for {label}: {resp.status_code} {resp.text[:200]}")
                raise StopUser()
            data = resp.json()
            token = data.get("access_token") or (data.get("data") or {}).get("access_token")
            if not token:
                resp.failure(f"No access_token in login response for {label}")
                raise StopUser()
            self.auth_headers = {"Authorization": f"Bearer {token}"}
            self._label = label
            log.info("Logged in as %s (%s)", email, label)

    def _get(self, url: str, name: str = None, threshold_ms: int = THRESHOLD_STANDARD_MS, **kwargs):
        name = name or f"GET {url}"
        with self.client.get(
            url, headers=self.auth_headers, catch_response=True, name=name, **kwargs
        ) as resp:
            if resp.status_code == 200:
                _check_threshold(resp, name, threshold_ms)
                resp.success()
            elif resp.status_code in (401, 403):
                resp.failure(f"{resp.status_code} — RBAC error on {name}")
            else:
                resp.failure(f"{resp.status_code} — {resp.text[:120]}")
        return resp

    def _post(self, url: str, payload: dict, name: str = None,
              threshold_ms: int = THRESHOLD_STANDARD_MS, expected_status: int = 201, **kwargs):
        name = name or f"POST {url}"
        with self.client.post(
            url, json=payload, headers=self.auth_headers,
            catch_response=True, name=name, **kwargs
        ) as resp:
            if resp.status_code == expected_status:
                _check_threshold(resp, name, threshold_ms)
                resp.success()
                try:
                    return resp.json()
                except Exception:
                    return {}
            elif resp.status_code in (401, 403):
                resp.failure(f"{resp.status_code} — RBAC error on {name}")
            else:
                resp.failure(f"{resp.status_code} — {resp.text[:120]}")
        return {}


# ---------------------------------------------------------------------------
# User class 1: Standard read-heavy staff member (sales reps, support agents)
# Represents the majority of concurrent users — browsing lists and profiles.
# ---------------------------------------------------------------------------
class ReadHeavyUser(OpsraBaseUser):
    """
    Simulates a sales rep or support agent cycling through their daily workflow:
    checking lead lists, ticket queues, customer profiles, and tasks.
    Weight 7 — represents 7 out of every 10 simulated users.
    """
    weight = 7
    wait_time = between(2, 6)

    @task(5)
    def browse_leads(self):
        self._get("/api/v1/leads", "GET /leads (list)")

    @task(3)
    def browse_leads_by_stage(self):
        stage = random.choice(["new", "contacted", "demo_done", "proposal_sent"])
        self._get(f"/api/v1/leads?stage={stage}", "GET /leads?stage=X")

    @task(3)
    def browse_tickets(self):
        self._get("/api/v1/tickets", "GET /tickets (list)")

    @task(2)
    def browse_open_tickets(self):
        self._get("/api/v1/tickets?status=open", "GET /tickets?status=open")

    @task(2)
    def browse_customers(self):
        self._get("/api/v1/customers", "GET /customers (list)")

    @task(2)
    def browse_tasks(self):
        self._get("/api/v1/tasks", "GET /tasks (list)")

    @task(2)
    def check_my_profile(self):
        self._get("/api/v1/auth/me", "GET /auth/me")

    @task(1)
    def browse_subscriptions(self):
        self._get("/api/v1/subscriptions", "GET /subscriptions")

    @task(1)
    def browse_broadcasts(self):
        self._get("/api/v1/broadcasts", "GET /broadcasts")

    @task(1)
    def browse_templates(self):
        self._get("/api/v1/templates", "GET /templates")

    @task(1)
    def search_leads(self):
        query = random.choice(["store", "pharma", "lagos", "tech", "food"])
        self._get(
            f"/api/v1/leads?search={query}",
            "GET /leads?search=X",
            threshold_ms=THRESHOLD_SEARCH_MS,
        )

    @task(1)
    def search_tickets(self):
        query = random.choice(["payment", "login", "error", "sync", "slow"])
        self._get(
            f"/api/v1/tickets?search={query}",
            "GET /tickets?search=X",
            threshold_ms=THRESHOLD_SEARCH_MS,
        )


# ---------------------------------------------------------------------------
# User class 2: Dashboard-heavy manager/owner
# Polls the executive dashboard and reporting views frequently.
# Weight 2 — represents managers / CEO.
# ---------------------------------------------------------------------------
class DashboardUser(OpsraBaseUser):
    """
    Simulates an ops manager or CEO refreshing the executive dashboard,
    health indicators, and reports. Dashboard refresh rate in the DRD
    is every 60 seconds — this simulates that polling pattern.
    Logs in as owner or ops_manager only — growth analytics routes
    are restricted to these roles.
    """
    weight = 2
    wait_time = between(3, 8)

    def on_start(self):
        account = random.choice(MANAGER_ACCOUNTS)
        self._login(account["email"], account["password"], account["label"])

    @task(6)
    def poll_dashboard_metrics(self):
        self._get(
            "/api/v1/dashboard/metrics",
            "GET /dashboard/metrics",
            threshold_ms=THRESHOLD_DASHBOARD_MS,
        )

    @task(4)
    def view_growth_overview(self):
        self._get("/api/v1/analytics/growth/overview", "GET /analytics/growth/overview")

    @task(3)
    def view_growth_funnel(self):
        self._get("/api/v1/analytics/growth/funnel", "GET /analytics/growth/funnel")

    @task(2)
    def view_pipeline_at_risk(self):
        self._get("/api/v1/analytics/growth/pipeline-at-risk", "GET /analytics/growth/pipeline-at-risk")

    @task(2)
    def view_growth_channels(self):
        self._get("/api/v1/analytics/growth/channels", "GET /analytics/growth/channels")

    @task(2)
    def view_win_loss(self):
        self._get("/api/v1/analytics/growth/win-loss", "GET /analytics/growth/win-loss")

    @task(1)
    def view_sales_reps(self):
        self._get("/api/v1/analytics/growth/sales-reps", "GET /analytics/growth/sales-reps")

    @task(1)
    def check_anomalies(self):
        self._get("/api/v1/analytics/growth/insights/anomalies", "GET /anomalies")


# ---------------------------------------------------------------------------
# User class 3: Write-heavy operations user
# Creates leads, logs interactions, creates tickets, updates tasks.
# Weight 1 — one "power user" in the simulated team.
# ---------------------------------------------------------------------------
class WriteHeavyUser(OpsraBaseUser):
    """
    Simulates a staff member actively creating records throughout the day:
    manual leads, support tickets, tasks, and AI-powered scoring requests.
    Also exercises the AI ask-your-data endpoint.
    """
    weight = 1
    wait_time = between(4, 10)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache lead IDs and their known stage
        self._leads: dict[str, str] = {}   # id → stage
        self._ticket_ids: list[str] = []

    @task(4)
    def create_lead(self):
        data = self._post(
            "/api/v1/leads",
            lead_create_payload(),
            name="POST /leads (create)",
            expected_status=201,
        )
        lid = (data.get("data") or data).get("id")
        if lid:
            self._leads[lid] = "new"
            if len(self._leads) > 20:
                oldest = next(iter(self._leads))
                del self._leads[oldest]

    @task(3)
    def create_ticket(self):
        data = self._post(
            "/api/v1/tickets",
            ticket_create_payload(),
            name="POST /tickets (create)",
            expected_status=201,
        )
        tid = (data.get("data") or data).get("id")
        if tid:
            self._ticket_ids.append(tid)
            if len(self._ticket_ids) > 20:
                self._ticket_ids.pop(0)

    @task(2)
    def create_task(self):
        self._post(
            "/api/v1/tasks",
            task_create_payload(),
            name="POST /tasks (create)",
            expected_status=201,
        )

    @task(2)
    def score_a_lead(self):
        """Trigger AI lead scoring — Claude Sonnet — threshold 5 s."""
        if not self._leads:
            return
        lid = random.choice(list(self._leads.keys()))
        self._post(
            f"/api/v1/leads/{lid}/score",
            {},
            name="POST /leads/{id}/score (AI)",
            threshold_ms=THRESHOLD_AI_MS,
            expected_status=200,
        )

    @task(2)
    def ask_your_data(self):
        """AI natural-language query over live data — threshold 5 s."""
        self._post(
            "/api/v1/ask",
            ask_payload(),
            name="POST /ask (AI)",
            threshold_ms=THRESHOLD_AI_MS,
            expected_status=200,
        )

    @task(1)
    def read_lead_timeline(self):
        if not self._leads:
            return
        lid = random.choice(list(self._leads.keys()))
        self._get(f"/api/v1/leads/{lid}/timeline", "GET /leads/{id}/timeline")

    @task(1)
    def move_lead_stage(self):
        """Move a lead from new → contacted. Only attempt on leads still at new."""
        new_leads = [lid for lid, stage in self._leads.items() if stage == "new"]
        if not new_leads:
            return
        lid = random.choice(new_leads)
        result = self._post(
            f"/api/v1/leads/{lid}/move-stage",
            {"new_stage": "contacted"},
            name="POST /leads/{id}/move-stage",
            expected_status=200,
        )
        if result:
            self._leads[lid] = "contacted"

    @task(1)
    def resolve_ticket(self):
        if not self._ticket_ids:
            return
        tid = random.choice(self._ticket_ids)
        self._post(
            f"/api/v1/tickets/{tid}/resolve",
            {"resolution_notes": "Resolved by load test automation."},
            name="POST /tickets/{id}/resolve",
            expected_status=200,
        )
