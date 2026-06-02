"""
app/services/performance_service.py
-------------------------------------
Business logic for PERF-1 — Performance & Operations Hub.

Efficiency rules (mandatory — see PERF-1 spec):
  E1 — asyncio.gather for all independent fetches
  E2 — fetch wide once, group in Python (no N+1 loops)
  E3 — tiered Redis caching (check before DB, invalidate on writes)
  E4 — selective column selects (never SELECT *)
  E5 — indexes defined in migration SQL

Security rules applied:
  S1  — org_id always from JWT, never request body
  S3  — Pydantic field constraints on all inputs
  S4  — free-text fields max 500–1000 chars as per spec

Pattern 33 — no ILIKE: all filtering in Python
Pattern 48 — notifications: resource_type + resource_id only
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Optional

import bcrypt as _bcrypt_lib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis client — optional (fail-open if Redis unavailable)
# ---------------------------------------------------------------------------
try:
    import redis as redis_lib
    _redis_url = os.environ.get("REDIS_URL", "")

    def _get_redis():
        if not _redis_url:
            return None
        ssl = _redis_url.startswith("rediss://")
        return redis_lib.from_url(
            _redis_url,
            decode_responses=True,
            ssl_cert_reqs=None if ssl else "required",
        )
except ImportError:
    _get_redis = lambda: None  # noqa: E731

# ---------------------------------------------------------------------------
# Cache TTLs (seconds)
# ---------------------------------------------------------------------------
_TTL_HEALTH      = 300   # 5 min
_TTL_SCORECARD   = 120   # 2 min
_TTL_STAFF       = 60    # 1 min
_TTL_TEMPLATES   = 1800  # 30 min
_TTL_OWNER_DASH  = 120   # 2 min


def _cache_get(key: str) -> Any | None:
    try:
        r = _get_redis()
        if r is None:
            return None
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("Redis GET failed key=%s: %s", key, exc)
        return None


def _cache_set(key: str, value: Any, ttl: int) -> None:
    try:
        r = _get_redis()
        if r is None:
            return
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception as exc:
        logger.warning("Redis SET failed key=%s: %s", key, exc)


def _cache_delete(*keys: str) -> None:
    try:
        r = _get_redis()
        if r is None:
            return
        r.delete(*keys)
    except Exception as exc:
        logger.warning("Redis DEL failed keys=%s: %s", keys, exc)


def _invalidate_org_perf_cache(org_id: str, user_id: str | None = None, month: str | None = None) -> None:
    """Invalidate all performance caches for an org on any write."""
    keys = [
        f"perf:health:{org_id}",
        f"perf:owner_dash:{org_id}",
    ]
    if month:
        keys.append(f"perf:scorecard:{org_id}:{month}")
    if user_id and month:
        keys.append(f"perf:staff:{org_id}:{user_id}:{month}")
    _cache_delete(*keys)


# ---------------------------------------------------------------------------
# KPI Template default seeds
# ---------------------------------------------------------------------------
_DEFAULT_TEMPLATES: list[dict] = [
    {"role_template": "sales_agent",    "kpi_name": "Leads Contacted",          "kpi_unit": "count",    "sort_order": 0},
    {"role_template": "sales_agent",    "kpi_name": "Demos Booked",             "kpi_unit": "count",    "sort_order": 1},
    {"role_template": "sales_agent",    "kpi_name": "Deals Closed",             "kpi_unit": "count",    "sort_order": 2},
    {"role_template": "sales_agent",    "kpi_name": "Revenue Generated",        "kpi_unit": "currency", "sort_order": 3},
    {"role_template": "support_agent",  "kpi_name": "Tickets Resolved",         "kpi_unit": "count",    "sort_order": 0},
    {"role_template": "support_agent",  "kpi_name": "Avg Resolution Time",      "kpi_unit": "minutes",  "sort_order": 1},
    {"role_template": "support_agent",  "kpi_name": "Customer Satisfaction",    "kpi_unit": "count",    "sort_order": 2},
    {"role_template": "ops_manager",    "kpi_name": "Tasks Completed",          "kpi_unit": "count",    "sort_order": 0},
    {"role_template": "ops_manager",    "kpi_name": "Issues Resolved",          "kpi_unit": "count",    "sort_order": 1},
    {"role_template": "content_creator","kpi_name": "Posts Published",          "kpi_unit": "count",    "sort_order": 0},
    {"role_template": "content_creator","kpi_name": "Campaigns Launched",       "kpi_unit": "count",    "sort_order": 1},
    {"role_template": "website_manager","kpi_name": "Pages Updated",            "kpi_unit": "count",    "sort_order": 0},
    {"role_template": "website_manager","kpi_name": "Bugs Fixed",               "kpi_unit": "count",    "sort_order": 1},
    {"role_template": "general_staff",  "kpi_name": "Tasks Completed",          "kpi_unit": "count",    "sort_order": 0},
    {"role_template": "general_staff",  "kpi_name": "Attendance Days",          "kpi_unit": "count",    "sort_order": 1},
]


def _seed_kpi_templates(db, org_id: str) -> None:
    """
    Lazy seed: called on first GET /kpi-templates for an org.
    Only inserts role+name combos that don't already exist.
    """
    existing = db.table("kpi_templates").select("role_template, kpi_name").eq("org_id", org_id).execute()
    existing_set = {(r["role_template"], r["kpi_name"]) for r in (existing.data or [])}
    to_insert = [
        {**t, "org_id": org_id}
        for t in _DEFAULT_TEMPLATES
        if (t["role_template"], t["kpi_name"]) not in existing_set
    ]
    if to_insert:
        db.table("kpi_templates").insert(to_insert).execute()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_start(month_str: str) -> date:
    """Parse YYYY-MM to the 1st of that month as a date object."""
    parts = month_str.split("-")
    return date(int(parts[0]), int(parts[1]), 1)


def _current_month_str() -> str:
    today = date.today()
    return f"{today.year}-{today.month:02d}"


def _days_in_month(d: date) -> int:
    if d.month == 12:
        return 31
    return (date(d.year, d.month + 1, 1) - timedelta(days=1)).day


def _pace_status(actual: float, target: float, days_elapsed: int, days_in_month: int) -> str:
    """
    Returns 'Ahead' | 'On Track' | 'Behind' based on actual vs pace.
    Pace = target * (days_elapsed / days_in_month).
    """
    if target <= 0 or days_in_month <= 0:
        return "On Track"
    pace = target * (days_elapsed / days_in_month)
    if pace == 0:
        return "On Track"
    ratio = actual / pace
    if ratio >= 1.1:
        return "Ahead"
    if ratio >= 0.9:
        return "On Track"
    return "Behind"


def _kpi_achievement_pct(actual: float | None, target: float) -> float:
    if actual is None or target <= 0:
        return 0.0
    return min(100.0, round((actual / target) * 100, 1))


def _score_colour(pct: float) -> str:
    if pct >= 75:
        return "green"
    if pct >= 50:
        return "amber"
    return "red"


# ---------------------------------------------------------------------------
# KPI Templates
# ---------------------------------------------------------------------------

def get_kpi_templates(db, org_id: str) -> list[dict]:
    """E3: check Redis first. Lazy-seed defaults on first call."""
    cache_key = f"perf:kpi_templates:{org_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    _seed_kpi_templates(db, org_id)
    result = (
        db.table("kpi_templates")
        .select("id, role_template, kpi_name, kpi_unit, sort_order, is_active, created_at")
        .eq("org_id", org_id)
        .order("role_template")
        .order("sort_order")
        .execute()
    )
    data = result.data or []
    _cache_set(cache_key, data, _TTL_TEMPLATES)
    return data


def create_kpi_template(db, org_id: str, role_template: str, kpi_name: str,
                         kpi_unit: str | None, sort_order: int) -> dict:
    row = db.table("kpi_templates").insert({
        "org_id": org_id,
        "role_template": role_template,
        "kpi_name": kpi_name,
        "kpi_unit": kpi_unit,
        "sort_order": sort_order,
    }).execute()
    _cache_delete(f"perf:kpi_templates:{org_id}")
    return row.data[0] if row.data else {}


def update_kpi_template(db, org_id: str, template_id: str, updates: dict) -> dict:
    row = (
        db.table("kpi_templates")
        .update(updates)
        .eq("id", template_id)
        .eq("org_id", org_id)
        .execute()
    )
    _cache_delete(f"perf:kpi_templates:{org_id}")
    return row.data[0] if row.data else {}


def soft_delete_kpi_template(db, org_id: str, template_id: str) -> dict:
    return update_kpi_template(db, org_id, template_id, {"is_active": False})


# ---------------------------------------------------------------------------
# KPI Targets
# ---------------------------------------------------------------------------

def get_targets_for_user_month(db, org_id: str, user_id: str, month: str) -> list[dict]:
    """E3: check Redis first."""
    cache_key = f"perf:staff:{org_id}:{user_id}:{month}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    month_date = _month_start(month)
    result = (
        db.table("staff_kpi_targets")
        .select("id, kpi_name, kpi_unit, target_value, actual_value, notes, acknowledged_at, month_start, updated_at")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .eq("month_start", str(month_date))
        .execute()
    )
    data = result.data or []
    _cache_set(cache_key, data, _TTL_STAFF)
    return data


def set_targets(db, org_id: str, user_id: str, month: str,
                targets: list[dict], created_by: str) -> list[dict]:
    """
    Upsert a list of KPI targets for a user+month.
    targets: [{"kpi_name": str, "kpi_unit": str|None, "target_value": float, "notes": str|None}]
    """
    month_date = str(_month_start(month))
    inserted = []
    for t in targets:
        existing = (
            db.table("staff_kpi_targets")
            .select("id")
            .eq("org_id", org_id)
            .eq("user_id", user_id)
            .eq("kpi_name", t["kpi_name"])
            .eq("month_start", month_date)
            .limit(1)
            .execute()
        )
        payload = {
            "org_id": org_id,
            "user_id": user_id,
            "kpi_name": t["kpi_name"],
            "kpi_unit": t.get("kpi_unit"),
            "target_value": t["target_value"],
            "notes": t.get("notes"),
            "month_start": month_date,
            "updated_at": datetime.utcnow().isoformat(),
            "created_by": created_by,
        }
        if existing.data:
            row = (
                db.table("staff_kpi_targets")
                .update(payload)
                .eq("id", existing.data[0]["id"])
                .execute()
            )
        else:
            row = db.table("staff_kpi_targets").insert(payload).execute()
        if row.data:
            inserted.append(row.data[0])

    _invalidate_org_perf_cache(org_id, user_id, month)
    return inserted


def acknowledge_targets(db, org_id: str, user_id: str, month: str) -> bool:
    """Staff member confirms they have seen their targets for this month."""
    month_date = str(_month_start(month))
    db.table("staff_kpi_targets").update({
        "acknowledged_at": datetime.utcnow().isoformat(),
    }).eq("org_id", org_id).eq("user_id", user_id).eq("month_start", month_date).execute()
    _invalidate_org_perf_cache(org_id, user_id, month)
    return True


# ---------------------------------------------------------------------------
# Staff daily log
# ---------------------------------------------------------------------------

def create_staff_log(db, org_id: str, user_id: str, payload: dict) -> dict:
    """Staff self-log. entity_type='staff', entity_id=user_id."""
    row = db.table("performance_daily_logs").insert({
        "org_id": org_id,
        "entity_type": "staff",
        "entity_id": user_id,
        "log_date": str(payload.get("log_date", date.today())),
        "kpi_key": payload.get("kpi_key", ""),
        "kpi_label": payload.get("kpi_label", ""),
        "value": payload.get("value", 0),
        "label_value": payload.get("label_value"),
        "notes": payload.get("notes"),
        "attendance_status": payload.get("attendance_status", "present"),
        "activity_outcome": payload.get("activity_outcome"),
        "duration_minutes": payload.get("duration_minutes"),
        "blocker_note": payload.get("blocker_note"),
        "linked_record_type": payload.get("linked_record_type"),
        "linked_record_id": payload.get("linked_record_id"),
        "logged_via": "staff_app",
    }).execute()
    _invalidate_org_perf_cache(org_id, user_id, _current_month_str())
    return row.data[0] if row.data else {}


def update_staff_log(db, org_id: str, log_id: str, updates: dict) -> dict:
    """Manager override of any log row."""
    updates["updated_at"] = datetime.utcnow().isoformat()
    row = (
        db.table("performance_daily_logs")
        .update(updates)
        .eq("id", log_id)
        .eq("org_id", org_id)
        .execute()
    )
    _cache_delete(f"perf:owner_dash:{org_id}")
    return row.data[0] if row.data else {}


# ---------------------------------------------------------------------------
# Individual staff profile
# ---------------------------------------------------------------------------

async def _async_fetch(db, table: str, select: str, filters: list[tuple]) -> list[dict]:
    """Run a supabase query in a thread pool so asyncio.gather can parallelise."""
    import asyncio
    loop = asyncio.get_event_loop()

    def _run():
        q = db.table(table).select(select)
        for col, op, val in filters:
            if op == "eq":
                q = q.eq(col, val)
            elif op == "gte":
                q = q.gte(col, val)
            elif op == "lte":
                q = q.lte(col, val)
        return q.execute().data or []

    return await loop.run_in_executor(None, _run)


async def get_staff_profile(db, org_id: str, user_id: str, month: str) -> dict:
    """
    E1: parallel fetches for user info, targets, and log history.
    E3: Redis cache first.
    """
    cache_key = f"perf:staff:{org_id}:{user_id}:{month}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    month_date = _month_start(month)
    thirty_days_ago = str(date.today() - timedelta(days=30))

    user_data, targets, logs = await asyncio.gather(
        _async_fetch(db, "users", "id, full_name, email, roles(template)",
                     [("id", "eq", user_id), ("org_id", "eq", org_id)]),
        _async_fetch(db, "staff_kpi_targets",
                     "id, kpi_name, kpi_unit, target_value, actual_value, notes, acknowledged_at, month_start",
                     [("org_id", "eq", org_id), ("user_id", "eq", user_id),
                      ("month_start", "eq", str(month_date))]),
        _async_fetch(db, "performance_daily_logs",
                     "id, log_date, kpi_key, kpi_label, value, label_value, notes, "
                     "attendance_status, activity_outcome, duration_minutes, blocker_note, "
                     "approved_by_owner, owner_flag_note, created_at",
                     [("org_id", "eq", org_id), ("entity_id", "eq", user_id),
                      ("entity_type", "eq", "staff"), ("log_date", "gte", thirty_days_ago)]),
    )

    user_row = user_data[0] if user_data else {}
    role = (user_row.get("roles") or {}).get("template", "")

    # Calculate KPI achievement and pace
    today = date.today()
    days_elapsed = (today - month_date).days + 1
    days_in_month = _days_in_month(month_date)

    # Build running totals from logs this month (E2: slice in Python)
    logs_this_month = [
        l for l in logs
        if l.get("log_date", "") >= str(month_date)
    ]
    running_totals: dict[str, float] = {}
    for log in logs_this_month:
        key = log.get("kpi_key", "")
        if key:
            running_totals[key] = running_totals.get(key, 0) + float(log.get("value", 0) or 0)

    kpi_summary = []
    total_pct = 0.0
    for t in targets:
        actual = t.get("actual_value")
        if actual is None:
            # Fall back to running daily total if no manual actual set
            actual = running_totals.get(t["kpi_name"], None)
        target_val = float(t.get("target_value") or 0)
        pct = _kpi_achievement_pct(actual, target_val)
        total_pct += pct
        kpi_summary.append({
            **t,
            "actual_value": actual,
            "achievement_pct": pct,
            "pace": _pace_status(actual or 0, target_val, days_elapsed, days_in_month),
            "colour": _score_colour(pct),
        })

    score_pct = round(total_pct / len(targets), 1) if targets else 0.0

    result = {
        "user_id": user_id,
        "full_name": user_row.get("full_name", ""),
        "email": user_row.get("email", ""),
        "role": role,
        "month": month,
        "score_pct": score_pct,
        "score_colour": _score_colour(score_pct),
        "kpis": kpi_summary,
        "logs": sorted(logs, key=lambda x: x.get("log_date", ""), reverse=True),
        "acknowledged": any(t.get("acknowledged_at") for t in targets),
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
    }
    _cache_set(cache_key, result, _TTL_STAFF)
    return result


# ---------------------------------------------------------------------------
# Scorecard (all staff + contractors)
# ---------------------------------------------------------------------------

async def get_scorecard(db, org_id: str, month: str) -> list[dict]:
    """
    E1: parallel fetches for users, targets, logs, contractors.
    E2: group in Python, no N+1.
    E3: Redis cache.
    """
    cache_key = f"perf:scorecard:{org_id}:{month}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    month_date = _month_start(month)
    today = date.today()

    # E1: fire all fetches in parallel
    users_res, targets_res, logs_res, contractors_res, three_months_res = await asyncio.gather(
        # All active staff for org
        _async_fetch(db, "users",
                     "id, full_name, roles(template)",
                     [("org_id", "eq", org_id)]),
        # All KPI targets for this month (E2: fetch wide, group in Python)
        _async_fetch(db, "staff_kpi_targets",
                     "user_id, kpi_name, target_value, actual_value, month_start",
                     [("org_id", "eq", org_id), ("month_start", "eq", str(month_date))]),
        # All logs this month for staff
        _async_fetch(db, "performance_daily_logs",
                     "entity_id, entity_type, log_date, kpi_key, value, attendance_status",
                     [("org_id", "eq", org_id), ("log_date", "gte", str(month_date))]),
        # Contractors (for cross-entity view)
        _async_fetch(db, "contractors",
                     "id, full_name, role_title",
                     [("org_id", "eq", org_id)]),
        # Last 3 months of targets for sparkline (E2)
        _async_fetch(db, "staff_kpi_targets",
                     "user_id, kpi_name, target_value, actual_value, month_start",
                     [("org_id", "eq", org_id),
                      ("month_start", "gte", str(date(today.year, max(1, today.month - 2), 1)))]),
    )

    days_elapsed = (today - month_date).days + 1
    days_in_month = _days_in_month(month_date)

    # E2: group targets by user
    targets_by_user: dict[str, list] = {}
    for t in targets_res:
        targets_by_user.setdefault(t["user_id"], []).append(t)

    # E2: group logs by entity
    logs_by_entity: dict[str, list] = {}
    for log in logs_res:
        logs_by_entity.setdefault(log["entity_id"], []).append(log)

    # E2: group 3-month targets by user
    history_by_user: dict[str, list] = {}
    for t in three_months_res:
        history_by_user.setdefault(t["user_id"], []).append(t)

    def _build_sparkline(user_id: str) -> list[dict]:
        """3 months of score % for sparkline."""
        rows = history_by_user.get(user_id, [])
        months: dict[str, list] = {}
        for t in rows:
            m = str(t["month_start"])[:7]
            months.setdefault(m, []).append(t)
        result = []
        for m_str in sorted(months.keys()):
            m_targets = months[m_str]
            if not m_targets:
                continue
            total = sum(_kpi_achievement_pct(t.get("actual_value"), float(t.get("target_value") or 0))
                        for t in m_targets)
            result.append({"month": m_str, "score_pct": round(total / len(m_targets), 1)})
        return result[-3:]

    def _today_attendance(entity_id: str) -> str:
        today_str = str(today)
        logs_today = [l for l in logs_by_entity.get(entity_id, []) if l.get("log_date") == today_str]
        return logs_today[0].get("attendance_status", "—") if logs_today else "—"

    def _last_log_date(entity_id: str) -> str | None:
        entity_logs = logs_by_entity.get(entity_id, [])
        if not entity_logs:
            return None
        return max(l.get("log_date", "") for l in entity_logs) or None

    def _last_log_colour(last_date: str | None) -> str:
        if not last_date:
            return "red"
        delta = (today - date.fromisoformat(last_date)).days
        if delta <= 1:
            return "green"
        if delta == 2:  # >1 day = amber per spec
            return "amber"
        return "red"

    rows = []

    # Staff rows
    for user in users_res:
        uid = user["id"]
        role = (user.get("roles") or {}).get("template", "general_staff")
        user_targets = targets_by_user.get(uid, [])
        if not user_targets:
            score_pct = 0.0
        else:
            total = sum(_kpi_achievement_pct(t.get("actual_value"), float(t.get("target_value") or 0))
                        for t in user_targets)
            score_pct = round(total / len(user_targets), 1)

        # Running totals from daily logs as fallback
        user_logs = logs_by_entity.get(uid, [])
        running: dict[str, float] = {}
        for log in user_logs:
            k = log.get("kpi_key", "")
            if k:
                running[k] = running.get(k, 0) + float(log.get("value", 0) or 0)

        # Re-score using running totals where no manual actual
        if user_targets:
            total = 0.0
            for t in user_targets:
                actual = t.get("actual_value")
                if actual is None:
                    actual = running.get(t["kpi_name"])
                total += _kpi_achievement_pct(actual, float(t.get("target_value") or 0))
            score_pct = round(total / len(user_targets), 1)

        last_date = _last_log_date(uid)
        pace = _pace_status(score_pct, 100, days_elapsed, days_in_month)

        rows.append({
            "entity_type": "staff",
            "entity_id": uid,
            "name": user.get("full_name", ""),
            "role": role,
            "score_pct": score_pct,
            "score_colour": _score_colour(score_pct),
            "pace": pace,
            "attendance_today": _today_attendance(uid),
            "last_log_date": last_date,
            "last_log_colour": _last_log_colour(last_date),
            "sparkline": _build_sparkline(uid),
        })

    # Contractor rows (cross-entity view — data from contractors table)
    for c in contractors_res:
        cid = c["id"]
        last_date = _last_log_date(cid)
        rows.append({
            "entity_type": "contractor",
            "entity_id": cid,
            "name": c.get("full_name", ""),
            "role": c.get("role_title", "contractor"),
            "score_pct": None,  # populated from contractor KPI actuals if needed
            "score_colour": "gray",
            "pace": "—",
            "attendance_today": _today_attendance(cid),
            "last_log_date": last_date,
            "last_log_colour": _last_log_colour(last_date),
            "sparkline": [],
        })

    _cache_set(cache_key, rows, _TTL_SCORECARD)
    return rows


# ---------------------------------------------------------------------------
# Health Score
# ---------------------------------------------------------------------------

async def get_health_score(db, org_id: str) -> dict:
    """
    Computes org health score from 4 components.
    E1: parallel fetch of all data needed.
    E3: Redis cache 5 min.
    """
    cache_key = f"perf:health:{org_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    today = date.today()
    month_start_str = str(date(today.year, today.month, 1))
    days_in_month = _days_in_month(date(today.year, today.month, 1))
    days_elapsed = today.day

    # E1: fire all in parallel
    org_res, targets_res, tasks_res, tickets_res, leads_res = await asyncio.gather(
        _async_fetch(db, "organisations",
                     "id, health_score_weights, monthly_revenue_target",
                     [("id", "eq", org_id)]),
        _async_fetch(db, "staff_kpi_targets",
                     "target_value, actual_value, month_start",
                     [("org_id", "eq", org_id), ("month_start", "eq", month_start_str)]),
        _async_fetch(db, "tasks",
                     "id, status, due_date",
                     [("org_id", "eq", org_id), ("due_date", "gte", month_start_str)]),
        _async_fetch(db, "tickets",
                     "id, status, created_at",
                     [("org_id", "eq", org_id)]),
        _async_fetch(db, "leads",
                     "id, deal_value, stage, created_at",
                     [("org_id", "eq", org_id), ("created_at", "gte", month_start_str)]),
    )

    org = org_res[0] if org_res else {}
    raw_weights = org.get("health_score_weights") or {}
    # Handle jsonb returned as string or dict
    if isinstance(raw_weights, str):
        try:
            raw_weights = json.loads(raw_weights)
        except Exception:
            raw_weights = {}
    weights = {
        "sales": int(raw_weights.get("sales", 35)),
        "staff": int(raw_weights.get("staff", 25)),
        "tasks": int(raw_weights.get("tasks", 20)),
        "support": int(raw_weights.get("support", 20)),
    }

    # --- Sales score ---
    revenue_target = float(org.get("monthly_revenue_target") or 0)
    revenue_actual = sum(float(l.get("deal_value") or 0) for l in leads_res
                         if l.get("stage") == "converted")
    if revenue_target > 0:
        pace = revenue_target * (days_elapsed / days_in_month)
        sales_score = min(100.0, (revenue_actual / pace * 100) if pace > 0 else 0.0)
    else:
        sales_score = 100.0  # no target set → no penalty

    # --- Staff score ---
    if targets_res:
        total_pct = sum(_kpi_achievement_pct(t.get("actual_value"), float(t.get("target_value") or 0))
                        for t in targets_res)
        staff_score = round(total_pct / len(targets_res), 1)
    else:
        staff_score = 100.0

    # --- Tasks score ---
    total_tasks = len(tasks_res)
    completed_tasks = sum(1 for t in tasks_res if t.get("status") == "completed")
    tasks_score = round((completed_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 100.0

    # --- Support score ---
    total_tickets = len(tickets_res)
    resolved_tickets = sum(1 for t in tickets_res if t.get("status") == "resolved")
    overdue_tickets = sum(
        1 for t in tickets_res
        if t.get("status") not in ("resolved", "closed")
    )
    if total_tickets > 0:
        support_score = max(0.0, round((resolved_tickets / total_tickets) * 100 - overdue_tickets * 5, 1))
    else:
        support_score = 100.0

    # --- Weighted health score ---
    health = (
        sales_score   * weights["sales"]   / 100 +
        staff_score   * weights["staff"]   / 100 +
        tasks_score   * weights["tasks"]   / 100 +
        support_score * weights["support"] / 100
    )
    health = round(health, 1)

    result = {
        "health_score": health,
        "colour": _score_colour(health),
        "components": {
            "sales":   {"score": round(sales_score, 1),   "weight": weights["sales"]},
            "staff":   {"score": round(staff_score, 1),   "weight": weights["staff"]},
            "tasks":   {"score": round(tasks_score, 1),   "weight": weights["tasks"]},
            "support": {"score": round(support_score, 1), "weight": weights["support"]},
        },
        "weights": weights,
    }
    _cache_set(cache_key, result, _TTL_HEALTH)
    return result


# ---------------------------------------------------------------------------
# Owner Dashboard Token & PIN
# ---------------------------------------------------------------------------

def get_or_create_owner_dashboard_token(db, org_id: str) -> dict:
    """Return existing token or generate a new one. Never expose PIN hash."""
    org = db.table("organisations").select(
        "owner_dashboard_token, owner_dashboard_pin"
    ).eq("id", org_id).single().execute()
    row = org.data or {}
    token = row.get("owner_dashboard_token")
    if not token:
        token = secrets.token_urlsafe(32)
        db.table("organisations").update({"owner_dashboard_token": token}).eq("id", org_id).execute()
    return {
        "token": token,
        "pin_set": bool(row.get("owner_dashboard_pin")),
    }


def set_owner_dashboard_pin(db, org_id: str, pin: str) -> bool:
    """Hash and store owner dashboard PIN."""
    hashed = _bcrypt_lib.hashpw(pin.encode(), _bcrypt_lib.gensalt()).decode()
    db.table("organisations").update({"owner_dashboard_pin": hashed}).eq("id", org_id).execute()
    return True


def verify_owner_dashboard_pin(db, token: str, pin: str) -> dict | None:
    """
    Verify PIN for a given token. Returns org data or None.
    Caller handles brute-force lockout via Redis.
    """
    org = db.table("organisations").select(
        "id, name, owner_dashboard_pin, health_score_weights"
    ).eq("owner_dashboard_token", token).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        return None
    stored_hash = row.get("owner_dashboard_pin")
    if not stored_hash:
        return None
    try:
        valid = _bcrypt_lib.checkpw(pin.encode(), stored_hash.encode())
    except Exception:
        valid = False
    if not valid:
        return None
    return row


def generate_owner_session_token(org_id: str, token: str) -> str:
    """Short-lived session token: HMAC of org_id+dashboard_token+timestamp (24h)."""
    import hmac
    secret = os.environ.get("SECRET_KEY", "opsra-perf-secret")
    expires = int((datetime.utcnow() + timedelta(hours=24)).timestamp())
    msg = f"{org_id}:{token}:{expires}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}:{sig}"


def verify_owner_session_token(raw_token: str, org_id: str, dashboard_token: str) -> bool:
    """Verify a session token produced by generate_owner_session_token."""
    import hmac as hmac_lib
    try:
        parts = raw_token.split(":")
        if len(parts) != 4:
            return False
        o_id, d_token, expires_str, sig = parts
        if o_id != org_id or d_token != dashboard_token:
            return False
        if int(expires_str) < int(datetime.utcnow().timestamp()):
            return False
        secret = os.environ.get("SECRET_KEY", "opsra-perf-secret")
        msg = f"{o_id}:{d_token}:{expires_str}"
        expected = hmac_lib.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return hmac_lib.compare_digest(sig, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Owner Dashboard — 5 panels
# ---------------------------------------------------------------------------

async def get_owner_dashboard_panels(db, org_id: str) -> dict:
    """
    E1: parallel fetches for all 5 panels.
    E3: Redis cache 2 min.
    """
    cache_key = f"perf:owner_dash:{org_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    today = date.today()
    month_start_str = str(date(today.year, today.month, 1))
    today_str = str(today)

    targets_res, logs_today_res, tasks_res, tickets_res, issues_res, users_res = await asyncio.gather(
        _async_fetch(db, "staff_kpi_targets",
                     "user_id, target_value, actual_value",
                     [("org_id", "eq", org_id), ("month_start", "eq", month_start_str)]),
        _async_fetch(db, "performance_daily_logs",
                     "id, entity_id, entity_type, kpi_key, kpi_label, value, attendance_status, approved_by_owner, created_at",
                     [("org_id", "eq", org_id), ("log_date", "eq", today_str)]),
        _async_fetch(db, "tasks",
                     "id, title, status, due_date, assigned_to",
                     [("org_id", "eq", org_id), ("due_date", "eq", today_str)]),
        _async_fetch(db, "tickets",
                     "id, status, created_at",
                     [("org_id", "eq", org_id)]),
        _async_fetch(db, "internal_issues",
                     "id, title, priority, status",
                     [("org_id", "eq", org_id)]),
        _async_fetch(db, "users",
                     "id, full_name, roles(template)",
                     [("org_id", "eq", org_id)]),
    )

    # Panel 2 — staff performance summary
    targets_by_user: dict[str, list] = {}
    for t in targets_res:
        targets_by_user.setdefault(t["user_id"], []).append(t)

    staff_summary = []
    for user in users_res:
        uid = user["id"]
        role = (user.get("roles") or {}).get("template", "")
        if role in ("owner",):
            continue
        user_targets = targets_by_user.get(uid, [])
        if not user_targets:
            continue
        total = sum(_kpi_achievement_pct(t.get("actual_value"), float(t.get("target_value") or 0))
                    for t in user_targets)
        score = round(total / len(user_targets), 1)
        staff_summary.append({"user_id": uid, "name": user.get("full_name", ""), "score": score})

    on_track = sum(1 for s in staff_summary if s["score"] >= 75)
    at_risk   = sum(1 for s in staff_summary if 50 <= s["score"] < 75)
    off_track = sum(1 for s in staff_summary if s["score"] < 50)

    # E2: build last-log-date index
    last_log_by_entity: dict[str, str] = {}
    for log in logs_today_res:
        eid = log["entity_id"]
        last_log_by_entity[eid] = log.get("log_date", today_str)

    overdue_log_staff = [
        s for s in staff_summary
        if s["user_id"] not in last_log_by_entity
    ]

    # Panel 3 — tasks
    completed_today = sum(1 for t in tasks_res if t.get("status") == "completed")
    pending_today   = sum(1 for t in tasks_res if t.get("status") != "completed")
    overdue_tasks = [
        {"id": t["id"], "title": t["title"], "assigned_to": t.get("assigned_to")}
        for t in tasks_res if t.get("status") not in ("completed", "cancelled")
        and (t.get("due_date") or "") < today_str
    ]

    # Panel 4 — support
    open_tickets = sum(1 for t in tickets_res if t.get("status") not in ("resolved", "closed"))
    overdue_tickets = open_tickets  # simplified: all open tickets from this month
    high_priority_issues = [
        {"id": i["id"], "title": i["title"]}
        for i in issues_res
        if i.get("priority") == "high" and i.get("status") != "resolved"
    ]

    # Panel 5 — pending approvals (logs submitted today, not yet approved)
    pending_approvals = [
        {
            "log_id": log["id"],
            "entity_id": log["entity_id"],
            "entity_type": log["entity_type"],
            "kpi_label": log.get("kpi_label", ""),
            "value": log.get("value"),
            "attendance_status": log.get("attendance_status", "present"),
        }
        for log in logs_today_res
        if not log.get("approved_by_owner")
    ]

    result = {
        "panel_staff": {
            "on_track": on_track,
            "at_risk": at_risk,
            "off_track": off_track,
            "at_risk_list": [s for s in staff_summary if s["score"] < 75],
            "overdue_log_alert": overdue_log_staff,
        },
        "panel_tasks": {
            "due_today_completed": completed_today,
            "due_today_pending": pending_today,
            "overdue": overdue_tasks,
        },
        "panel_support": {
            "open_tickets": open_tickets,
            "overdue_tickets": overdue_tickets,
            "high_priority_issues": high_priority_issues,
        },
        "panel_approvals": pending_approvals,
        "refreshed_at": datetime.utcnow().isoformat(),
    }
    _cache_set(cache_key, result, _TTL_OWNER_DASH)
    return result


def approve_log(db, org_id: str, log_id: str) -> bool:
    """Owner approves a daily log from external dashboard."""
    db.table("performance_daily_logs").update(
        {"approved_by_owner": True, "updated_at": datetime.utcnow().isoformat()}
    ).eq("id", log_id).eq("org_id", org_id).execute()
    _cache_delete(f"perf:owner_dash:{org_id}")
    return True


def flag_log(db, org_id: str, log_id: str, note: str, notif_user_ids: list[str]) -> bool:
    """
    Owner flags a log from external dashboard.
    Saves flag note and creates in-app notifications for owner + ops_managers.
    """
    db.table("performance_daily_logs").update({
        "owner_flag_note": note[:500],
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", log_id).eq("org_id", org_id).execute()

    # Notify owner + ops_manager (Pattern 48 — resource_type + resource_id)
    for uid in notif_user_ids:
        try:
            db.table("notifications").insert({
                "org_id": org_id,
                "user_id": uid,
                "type": "performance_flag",
                "title": "Log flagged by owner",
                "body": note[:200],
                "resource_type": "performance_log",
                "resource_id": log_id,
                "channel": "inapp",
                "is_read": False,
            }).execute()
        except Exception as exc:
            logger.warning("Failed to insert performance_flag notification uid=%s: %s", uid, exc)

    _cache_delete(f"perf:owner_dash:{org_id}")
    return True
