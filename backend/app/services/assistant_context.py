"""
app/services/assistant_context.py
----------------------------------
Per-role data gathering functions for Aria AI Assistant (M01-10b).

Each function returns a plain dict that is safe to JSON-serialise and
embed in a Haiku prompt.  Every sub-query is wrapped in try/except so
a single table miss never kills the whole context snapshot (S14).

Role map (from Technical Spec + DRD):
  owner / ops_manager   → full org overview
  sales_agent           → own leads, tasks, demos, unread messages
  customer_success      → customers, churn risk, open tickets, tasks
  support_agent         → assigned tickets, SLA status, messages
  finance               → renewals, payments, commissions
  affiliate_partner     → own commissions, referred leads, tasks
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe(data: list | None) -> list:
    return data or []


def _try(fn, fallback=None):
    """Run fn(); return fallback on any exception (S14 guard)."""
    try:
        return fn()
    except Exception:
        return fallback


# ─── Per-role context functions ───────────────────────────────────────────────

def get_owner_ops_context(db, org_id: str, user_id: str) -> dict[str, Any]:
    today = date.today().isoformat()
    in_7_days = (date.today() + timedelta(days=7)).isoformat()

    # Pipeline summary
    leads = _try(
        lambda: _safe(db.table("leads").select("stage, score").eq("org_id", org_id).execute().data)
    ) or []
    pipeline: dict[str, int] = {}
    for lead in leads:
        s = lead.get("stage", "unknown")
        pipeline[s] = pipeline.get(s, 0) + 1

    # Tasks
    tasks = _try(
        lambda: _safe(db.table("tasks").select("status, due_date").eq("org_id", org_id).execute().data)
    ) or []
    tasks_overdue   = sum(1 for t in tasks if t.get("status") != "done" and (t.get("due_date") or "") < today)
    tasks_due_today = sum(1 for t in tasks if t.get("status") != "done" and t.get("due_date") == today)

    # Tickets
    tickets = _try(
        lambda: _safe(db.table("tickets").select("status, sla_breached").eq("org_id", org_id).execute().data)
    ) or []
    open_tickets   = sum(1 for t in tickets if t.get("status") not in ("resolved", "closed"))
    sla_breached   = sum(1 for t in tickets if t.get("sla_breached"))

    # Subscriptions due in 7 days
    subs = _try(
        lambda: _safe(db.table("subscriptions").select("status, renewal_date").eq("org_id", org_id).execute().data)
    ) or []
    renewals_due = sum(
        1 for s in subs
        if s.get("status") == "active"
        and (s.get("renewal_date") or "") <= in_7_days
        and (s.get("renewal_date") or "") >= today
    )

    # Commissions pending
    comms = _try(
        lambda: _safe(
            db.table("commissions").select("status, amount")
            .eq("org_id", org_id).eq("status", "pending").execute().data
        )
    ) or []

    return {
        "pipeline_summary":             pipeline,
        "total_leads":                  len(leads),
        "tasks_overdue":                tasks_overdue,
        "tasks_due_today":              tasks_due_today,
        "open_tickets":                 open_tickets,
        "sla_breached_tickets":         sla_breached,
        "renewals_due_7_days":          renewals_due,
        "commissions_pending":          len(comms),
        "commissions_pending_amount":   sum(c.get("amount", 0) or 0 for c in comms),
    }


def get_sales_agent_context(db, org_id: str, user_id: str) -> dict[str, Any]:
    today = date.today().isoformat()

    # Own leads by stage
    leads = _try(
        lambda: _safe(
            db.table("leads").select("id, stage, score")
            .eq("org_id", org_id).eq("assigned_to", user_id).execute().data
        )
    ) or []
    by_stage: dict[str, int] = {}
    for lead in leads:
        s = lead.get("stage", "unknown")
        by_stage[s] = by_stage.get(s, 0) + 1
    lead_ids = [l["id"] for l in leads if l.get("id")]

    # Own tasks
    tasks = _try(
        lambda: _safe(
            db.table("tasks").select("status, due_date")
            .eq("org_id", org_id).eq("assigned_to", user_id).execute().data
        )
    ) or []
    tasks_overdue   = sum(1 for t in tasks if t.get("status") != "done" and (t.get("due_date") or "") < today)
    tasks_due_today = sum(1 for t in tasks if t.get("status") != "done" and t.get("due_date") == today)

    # Own demos upcoming — join via lead_ids (Pattern 45: .in_() whitelist)
    demos_upcoming = 0
    if lead_ids:
        demos = _try(
            lambda: _safe(
                db.table("lead_demos").select("id, scheduled_at, outcome")
                .in_("lead_id", lead_ids).execute().data
            )
        ) or []
        demos_upcoming = sum(
            1 for d in demos
            if d.get("outcome") == "pending"
            and (d.get("scheduled_at") or "") >= today
        )

    return {
        "leads_by_stage":       by_stage,
        "total_leads":          len(leads),
        "tasks_overdue":        tasks_overdue,
        "tasks_due_today":      tasks_due_today,
        "demos_upcoming":       demos_upcoming,
    }


def get_customer_success_context(db, org_id: str, user_id: str) -> dict[str, Any]:
    today = date.today().isoformat()

    # Customers (Pattern 36: no status column)
    customers = _try(
        lambda: _safe(
            db.table("customers").select("id, churn_risk").eq("org_id", org_id).execute().data
        )
    ) or []
    high_risk = sum(1 for c in customers if c.get("churn_risk") in ("high", "critical"))

    # Tickets
    tickets = _try(
        lambda: _safe(db.table("tickets").select("status, sla_breached").eq("org_id", org_id).execute().data)
    ) or []
    open_tickets = sum(1 for t in tickets if t.get("status") not in ("resolved", "closed"))
    sla_breached = sum(1 for t in tickets if t.get("sla_breached"))

    # Own tasks
    tasks = _try(
        lambda: _safe(
            db.table("tasks").select("status, due_date")
            .eq("org_id", org_id).eq("assigned_to", user_id).execute().data
        )
    ) or []
    tasks_pending = sum(1 for t in tasks if t.get("status") != "done")
    tasks_overdue = sum(1 for t in tasks if t.get("status") != "done" and (t.get("due_date") or "") < today)

    return {
        "total_customers":       len(customers),
        "high_churn_risk":       high_risk,
        "open_tickets":          open_tickets,
        "sla_breached_tickets":  sla_breached,
        "tasks_pending":         tasks_pending,
        "tasks_overdue":         tasks_overdue,
    }


def get_support_agent_context(db, org_id: str, user_id: str) -> dict[str, Any]:
    # Assigned tickets
    tickets = _try(
        lambda: _safe(
            db.table("tickets").select("id, status, sla_breached, assigned_to")
            .eq("org_id", org_id).execute().data
        )
    ) or []
    assigned       = [t for t in tickets if t.get("assigned_to") == user_id]
    open_assigned  = sum(1 for t in assigned if t.get("status") not in ("resolved", "closed"))
    sla_breached   = sum(1 for t in assigned if t.get("sla_breached"))

    # Total org-level open for broader picture
    total_open = sum(1 for t in tickets if t.get("status") not in ("resolved", "closed"))

    return {
        "assigned_tickets":          len(assigned),
        "open_assigned_tickets":     open_assigned,
        "sla_breached_tickets":      sla_breached,
        "total_org_open_tickets":    total_open,
    }


def get_finance_context(db, org_id: str, user_id: str) -> dict[str, Any]:
    today     = date.today().isoformat()
    in_30     = (date.today() + timedelta(days=30)).isoformat()

    subs = _try(
        lambda: _safe(
            db.table("subscriptions").select("status, renewal_date, amount")
            .eq("org_id", org_id).execute().data
        )
    ) or []
    due_30 = [
        s for s in subs
        if s.get("status") == "active"
        and today <= (s.get("renewal_date") or "") <= in_30
    ]

    comms = _try(
        lambda: _safe(
            db.table("commissions").select("status, amount").eq("org_id", org_id).execute().data
        )
    ) or []
    pending = [c for c in comms if c.get("status") == "pending"]
    paid    = [c for c in comms if c.get("status") == "paid"]

    return {
        "renewals_due_30_days":      len(due_30),
        "renewals_due_value":        sum(s.get("amount", 0) or 0 for s in due_30),
        "commissions_pending":       len(pending),
        "commissions_pending_amount": sum(c.get("amount", 0) or 0 for c in pending),
        "commissions_paid_total":    len(paid),
        "commissions_paid_amount":   sum(c.get("amount", 0) or 0 for c in paid),
    }


def get_affiliate_context(db, org_id: str, user_id: str) -> dict[str, Any]:
    today = date.today().isoformat()

    comms = _try(
        lambda: _safe(
            db.table("commissions").select("status, amount")
            .eq("org_id", org_id).eq("user_id", user_id).execute().data
        )
    ) or []
    pending = [c for c in comms if c.get("status") == "pending"]
    paid    = [c for c in comms if c.get("status") == "paid"]

    # Referred leads (assigned_to = user_id — affiliate partners are scoped, Pattern 39)
    leads = _try(
        lambda: _safe(
            db.table("leads").select("stage")
            .eq("org_id", org_id).eq("assigned_to", user_id).execute().data
        )
    ) or []
    by_stage: dict[str, int] = {}
    for lead in leads:
        s = lead.get("stage", "unknown")
        by_stage[s] = by_stage.get(s, 0) + 1

    # Own tasks
    tasks = _try(
        lambda: _safe(
            db.table("tasks").select("status, due_date")
            .eq("org_id", org_id).eq("assigned_to", user_id).execute().data
        )
    ) or []
    tasks_pending = sum(1 for t in tasks if t.get("status") != "done")
    tasks_overdue = sum(1 for t in tasks if t.get("status") != "done" and (t.get("due_date") or "") < today)

    return {
        "commissions_pending":           len(pending),
        "commissions_pending_amount":    sum(c.get("amount", 0) or 0 for c in pending),
        "commissions_paid":              len(paid),
        "commissions_paid_amount":       sum(c.get("amount", 0) or 0 for c in paid),
        "referred_leads_by_stage":       by_stage,
        "tasks_pending":                 tasks_pending,
        "tasks_overdue":                 tasks_overdue,
    }


# ─── Role dispatch map ────────────────────────────────────────────────────────

_ROLE_MAP = {
    "owner":             get_owner_ops_context,
    "ops_manager":       get_owner_ops_context,
    "sales_agent":       get_sales_agent_context,
    "customer_success":  get_customer_success_context,
    "support_agent":     get_support_agent_context,
    "finance":           get_finance_context,
    "affiliate_partner": get_affiliate_context,
}


def get_role_context(db, org_id: str, user_id: str, role_template: str) -> dict[str, Any]:
    """
    Return a role-scoped data snapshot for Haiku prompt injection.
    Falls back to owner context for unrecognised role templates.
    Looks up the fallback via _ROLE_MAP["owner"] at call time so tests
    can patch _ROLE_MAP entries and have fallback behaviour tested.
    """
    role_key = (role_template or "").lower()
    fn = _ROLE_MAP.get(role_key) or _ROLE_MAP.get("owner", get_owner_ops_context)
    return fn(db, org_id, user_id)