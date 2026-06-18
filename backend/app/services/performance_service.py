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
    {"role_template": "general_staff",  "kpi_name": "Tasks Completed",          "kpi_unit": "count",      "sort_order": 0},
    {"role_template": "general_staff",  "kpi_name": "Attendance Days",          "kpi_unit": "count",      "sort_order": 1},
    {"role_template": "ops_manager",     "kpi_name": "Team Revenue vs Target",   "kpi_unit": "percentage", "sort_order": 0},
    {"role_template": "ops_manager",     "kpi_name": "Team Conversion Rate",     "kpi_unit": "percentage", "sort_order": 1},
    {"role_template": "ops_manager",     "kpi_name": "Pipeline Value",           "kpi_unit": "currency",   "sort_order": 2},
    {"role_template": "ops_manager",     "kpi_name": "Rep Activity Compliance",  "kpi_unit": "percentage", "sort_order": 3},
    {"role_template": "ops_manager",     "kpi_name": "Lead Distribution Rate",   "kpi_unit": "count",      "sort_order": 4},
    {"role_template": "ops_manager",     "kpi_name": "Time to Close",            "kpi_unit": "days",       "sort_order": 5},
    {"role_template": "ops_manager",     "kpi_name": "Win / Loss Ratio",         "kpi_unit": "percentage", "sort_order": 6},
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


def _contractor_kpi_status(target_value, actual_value, kpi_type: str) -> str:
    """
    Mirrors app/routers/contractors.py:_kpi_status — kept in sync manually.
    Duplicated locally rather than imported to avoid a router→service
    reverse dependency. Returns: 'on_track' | 'at_risk' | 'off_track' | 'pending'
    """
    if actual_value is None:
        return "pending"
    if kpi_type == "leads_generated":
        pct = actual_value / target_value * 100 if target_value else 0
        if pct >= 100:
            return "on_track"
        if pct >= 70:
            return "at_risk"
        return "off_track"
    if kpi_type == "conversion_rate":
        if actual_value >= target_value:
            return "on_track"
        if actual_value >= target_value * 0.7:
            return "at_risk"
        return "off_track"
    if kpi_type == "response_time":
        if actual_value <= target_value:
            return "on_track"
        if actual_value <= target_value * 1.3:
            return "at_risk"
        return "off_track"
    return "pending"


def _contractor_risk_summary(actuals_by_month: dict, kpi_targets: list) -> dict:
    """
    Mirrors app/routers/contractors.py:_compute_risk_summary — kept in sync
    manually. Used to surface termination risk on the Owner Dashboard
    KPI tracker without importing across router/service boundaries.
    """
    if not kpi_targets or not actuals_by_month:
        return {
            "consecutive_months_off_track": 0,
            "at_termination_risk": False,
            "missed_kpi_months": [],
        }

    def _month_sort_key(label: str) -> int:
        try:
            return int(label.replace("Month", "").strip())
        except ValueError:
            return 0

    sorted_months = sorted(actuals_by_month.keys(), key=_month_sort_key)
    missed_kpi_months = []
    for month_label in sorted_months:
        month_actuals = actuals_by_month[month_label]
        all_off_track = True
        for kpi in kpi_targets:
            key      = kpi.get("key", "")
            kpi_type = kpi.get("kpi_type", "manual")
            target_val = kpi.get("target_value")
            actual_val = month_actuals.get(key)
            if _contractor_kpi_status(target_val, actual_val, kpi_type) != "off_track":
                all_off_track = False
                break
        if all_off_track:
            missed_kpi_months.append(month_label)

    consecutive = 0
    for month_label in reversed(sorted_months):
        if month_label in missed_kpi_months:
            consecutive += 1
        else:
            break

    return {
        "consecutive_months_off_track": consecutive,
        "at_termination_risk": consecutive >= 2,
        "missed_kpi_months": missed_kpi_months,
    }


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

    # Seed-on-demand: if no targets exist for this user+month, auto-seed from templates
    if not data:
        data = _seed_targets_for_user(db, org_id, user_id, month)

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


def _seed_targets_for_user(db, org_id: str, user_id: str, month: str, created_by: str | None = None) -> list[dict]:
    """
    Seed staff_kpi_targets for a user+month from kpi_templates.
    Called automatically when get_targets_for_user_month returns empty.
    """
    month_date = str(_month_start(month))

    try:
        user_res = db.table("users").select("roles(template)").eq("id", user_id).eq("org_id", org_id).limit(1).execute()
        user_row = (user_res.data or [{}])[0]
        role_template = (user_row.get("roles") or {}).get("template", "")
    except Exception as exc:
        logger.warning("_seed_targets_for_user: failed to fetch role for user %s: %s", user_id, exc)
        return []

    if not role_template:
        logger.info("_seed_targets_for_user: no role_template found for user %s, skipping", user_id)
        return []

    _seed_kpi_templates(db, org_id)

    try:
        tmpl_res = (
            db.table("kpi_templates")
            .select("kpi_name, kpi_unit, sort_order")
            .eq("org_id", org_id)
            .eq("role_template", role_template)
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )
        templates = tmpl_res.data or []
    except Exception as exc:
        logger.warning("_seed_targets_for_user: failed to fetch templates for role %s: %s", role_template, exc)
        return []

    if not templates:
        logger.info("_seed_targets_for_user: no active templates for role %s in org %s", role_template, org_id)
        return []

    inserted = []
    for t in templates:
        try:
            row = db.table("staff_kpi_targets").insert({
                "org_id": org_id,
                "user_id": user_id,
                "kpi_name": t["kpi_name"],
                "kpi_unit": t.get("kpi_unit"),
                "target_value": 0,
                "actual_value": None,
                "month_start": month_date,
                "created_by": created_by,
                "updated_at": datetime.utcnow().isoformat(),
            }).execute()
            if row.data:
                inserted.append(row.data[0])
        except Exception as exc:
            logger.warning("_seed_targets_for_user: insert failed for kpi %s: %s", t["kpi_name"], exc)

    logger.info("_seed_targets_for_user: seeded %d KPIs for user %s month %s", len(inserted), user_id, month)
    return inserted

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
                if val is None:
                    q = q.is_(col, "null")
                else:
                    q = q.eq(col, val)
            elif op == "gte":
                q = q.gte(col, val)
            elif op == "lte":
                q = q.lte(col, val)
            elif op == "is_null":
                q = q.is_(col, "null")
            elif op == "like":
                q = q.like(col, val)
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

    # Auto-compute KPIs from source data (on-demand, not persisted)
    auto_actuals: dict[str, float | None] = {}
    if role == "ops_manager":
        try:
            auto_actuals = _compute_sales_lead_kpis(db, org_id, month)
        except Exception as exc:
            logger.warning("ops_manager KPI auto-compute failed: %s", exc)
    elif role == "sales_agent":
        try:
            auto_actuals = _compute_sales_agent_kpis(db, org_id, user_id, month)
        except Exception as exc:
            logger.warning("sales_agent KPI auto-compute failed: %s", exc)

    kpi_summary = []
    total_pct = 0.0
    for t in targets:
        actual = t.get("actual_value")
        if actual is None:
            # Use auto-computed value if available for ops_manager sales lead KPIs
            if t["kpi_name"] in auto_actuals:
                actual = auto_actuals.get(t["kpi_name"])
            else:
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
        # Contractors (for cross-entity view) — confirmed columns: full_name, role_title
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

    # Contractor rows (cross-entity view — confirmed columns: full_name, role_title)
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

    # E1: fire all in parallel — tasks removed, leads used for both sales + leads conversion
    org_res, targets_res, tickets_res, leads_res = await asyncio.gather(
        _async_fetch(db, "organisations",
                     "id, health_score_weights, monthly_revenue_target",
                     [("id", "eq", org_id)]),
        _async_fetch(db, "staff_kpi_targets",
                     "target_value, actual_value, month_start",
                     [("org_id", "eq", org_id), ("month_start", "eq", month_start_str)]),
        # tickets: use sla_breached + resolved_at for overdue logic
        _async_fetch(db, "tickets",
                     "id, status, resolved_at, sla_breached, created_at",
                     [("org_id", "eq", org_id), ("deleted_at", "eq", None)]),
        _async_fetch(db, "leads",
                     "id, deal_value, stage, created_at, deleted_at",
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
    # Weights: tasks replaced with leads (conversion rate component)
    weights = {
        "revenue": int(raw_weights.get("revenue", raw_weights.get("sales", 35))),
        "staff":   int(raw_weights.get("staff", 25)),
        "leads":   int(raw_weights.get("leads",  raw_weights.get("tasks", 20))),
        "support": int(raw_weights.get("support", 20)),
    }

    # --- Revenue score ---
    active_leads_hs = [l for l in leads_res if not l.get("deleted_at")]
    revenue_target  = float(org.get("monthly_revenue_target") or 0)
    revenue_actual  = sum(
        float(l.get("deal_value") or 0) for l in active_leads_hs
        if l.get("stage") == "converted"
    )
    if revenue_target > 0:
        pace = revenue_target * (days_elapsed / days_in_month)
        revenue_score = min(100.0, (revenue_actual / pace * 100) if pace > 0 else 0.0)
    else:
        revenue_score = 100.0  # no target set → no penalty

    # --- Staff score ---
    if targets_res:
        total_pct = sum(_kpi_achievement_pct(t.get("actual_value"), float(t.get("target_value") or 0))
                        for t in targets_res)
        staff_score = round(total_pct / len(targets_res), 1)
    else:
        staff_score = 100.0
    staff_on_track = sum(1 for t in targets_res
                         if _kpi_achievement_pct(t.get("actual_value"), float(t.get("target_value") or 0)) >= 75)
    staff_total    = len(set(t.get("user_id", "") for t in targets_res)) if targets_res else 0

    # --- Leads conversion score ---
    total_leads_hs = len(active_leads_hs)
    converted_hs   = sum(1 for l in active_leads_hs if l.get("stage") == "converted")
    conv_rate_hs   = round(converted_hs / total_leads_hs * 100, 1) if total_leads_hs > 0 else 0.0
    # Score: conversion rate relative to a 20% benchmark (20% CR = 100 score)
    leads_score = min(100.0, round(conv_rate_hs / 20 * 100, 1)) if total_leads_hs > 0 else 100.0

    # --- Support score ---
    total_tickets    = len(tickets_res)
    resolved_tickets = sum(1 for t in tickets_res if t.get("resolved_at") is not None)
    overdue_tickets  = sum(1 for t in tickets_res if t.get("sla_breached") is True)
    if total_tickets > 0:
        support_score = max(0.0, round((resolved_tickets / total_tickets) * 100 - overdue_tickets * 5, 1))
    else:
        support_score = 100.0

    # --- Weighted health score ---
    health = (
        revenue_score * weights["revenue"] / 100 +
        staff_score   * weights["staff"]   / 100 +
        leads_score   * weights["leads"]   / 100 +
        support_score * weights["support"] / 100
    )
    health = round(health, 1)

    result = {
        "health_score": health,
        "colour": _score_colour(health),
        "components": {
            "revenue": {
                "score":  round(revenue_score, 1),
                "weight": weights["revenue"],
                "actual": round(revenue_actual, 0),
                "target": revenue_target,
                "label":  f"₦{int(revenue_actual):,} of ₦{int(revenue_target):,}" if revenue_target > 0 else f"₦{int(revenue_actual):,}",
            },
            "staff": {
                "score":  round(staff_score, 1),
                "weight": weights["staff"],
                "actual": staff_on_track,
                "target": staff_total,
                "label":  f"{staff_on_track} of {staff_total} on track" if staff_total > 0 else "No targets set",
            },
            "leads": {
                "score":  round(leads_score, 1),
                "weight": weights["leads"],
                "actual": conv_rate_hs,
                "target": 20,
                "label":  f"{conv_rate_hs}% conversion rate",
            },
            "support": {
                "score":  round(support_score, 1),
                "weight": weights["support"],
                "actual": total_tickets - resolved_tickets,
                "target": total_tickets,
                "label":  f"{total_tickets - resolved_tickets} open ticket{'s' if (total_tickets - resolved_tickets) != 1 else ''}",
            },
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
    """Short-lived session token stored as base64-encoded JSON payload + HMAC sig."""
    import hmac
    import base64
    secret = os.environ.get("SECRET_KEY", "opsra-perf-secret")
    expires = int((datetime.utcnow() + timedelta(hours=24)).timestamp())
    payload = base64.urlsafe_b64encode(
        json.dumps({"org_id": org_id, "token": token, "expires": expires}).encode()
    ).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_owner_session_token(raw_token: str, org_id: str, dashboard_token: str) -> bool:
    """Verify a session token produced by generate_owner_session_token."""
    import hmac as hmac_lib
    import base64
    try:
        parts = raw_token.rsplit(".", 1)
        if len(parts) != 2:
            return False
        payload_b64, sig = parts
        secret = os.environ.get("SECRET_KEY", "opsra-perf-secret")
        expected = hmac_lib.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac_lib.compare_digest(sig, expected):
            return False
        # Decode payload
        padding = 4 - len(payload_b64) % 4
        padded = payload_b64 + ("=" * (padding % 4))
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        if data.get("org_id") != org_id:
            return False
        if data.get("token") != dashboard_token:
            return False
        if int(data.get("expires", 0)) < int(datetime.utcnow().timestamp()):
            return False
        return True
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
        # tasks: confirmed column is due_at (timestamptz), not due_date
        _async_fetch(db, "tasks",
                     "id, title, status, due_at, assigned_to",
                     [("org_id", "eq", org_id), ("deleted_at", "eq", None)]),
        # tickets: use resolved_at and sla_breached — confirmed columns
        _async_fetch(db, "tickets",
                     "id, status, resolved_at, sla_breached, created_at",
                     [("org_id", "eq", org_id), ("deleted_at", "eq", None)]),
        _async_fetch(db, "internal_issues",
                     "id, title, priority, status",
                     [("org_id", "eq", org_id), ("deleted_at", "eq", None)]),
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

    # Panel 3 — tasks (due_at is timestamptz; compare as string prefix for date portion)
    today_iso = today_str + "T23:59:59"
    completed_today = sum(1 for t in tasks_res
                          if t.get("status") == "completed"
                          and (t.get("due_at") or "") >= today_str
                          and (t.get("due_at") or "") <= today_iso)
    pending_today   = sum(1 for t in tasks_res
                          if t.get("status") not in ("completed", "cancelled")
                          and (t.get("due_at") or "") >= today_str
                          and (t.get("due_at") or "") <= today_iso)
    overdue_tasks = [
        {"id": t["id"], "title": t["title"], "assigned_to": t.get("assigned_to")}
        for t in tasks_res
        if t.get("status") not in ("completed", "cancelled")
        and (t.get("due_at") or "") < today_str
    ]

    # Panel 4 — support (confirmed: resolved_at for resolution, sla_breached for overdue)
    open_tickets     = sum(1 for t in tickets_res if t.get("resolved_at") is None)
    overdue_tickets  = sum(1 for t in tickets_res if t.get("sla_breached") is True)
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


# ---------------------------------------------------------------------------
# Business Goals (PERF-1C)
# ---------------------------------------------------------------------------

_TTL_GOALS = 300  # 5 min


def _goals_cache_key(org_id: str, period_start: str) -> str:
    return f"perf:goals:{org_id}:{period_start}"


def get_business_goals(db, org_id: str, period_start: str) -> list[dict]:
    """
    Fetch active business goals for a period and compute live progress.
    E3: Redis cache 5 min.
    Progress is always computed live — never stored.
    """
    cache_key = _goals_cache_key(org_id, period_start)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    goals_res = (
        db.table("business_goals")
        .select("id, goal_name, goal_category, target_value, unit, period_type, period_start, notes")
        .eq("org_id", org_id)
        .eq("is_active", True)
        .eq("period_start", period_start)
        .order("goal_category")
        .execute()
    )
    goals = goals_res.data or []

    today = date.today()
    period_date   = date.fromisoformat(period_start)
    days_elapsed  = (today - period_date).days + 1
    days_in_period = _days_in_month(period_date)

    # E2: one fetch per source table, group in Python
    leads_res = (
        db.table("leads")
        .select("stage, deal_value, deleted_at")
        .eq("org_id", org_id)
        .gte("created_at", period_start)
        .execute()
    ).data or []

    tickets_res = (
        db.table("tickets")
        .select("resolved_at, deleted_at")
        .eq("org_id", org_id)
        .gte("created_at", period_start)
        .execute()
    ).data or []

    tasks_res = (
        db.table("tasks")
        .select("status, deleted_at")
        .eq("org_id", org_id)
        .gte("due_at", period_start)
        .execute()
    ).data or []

    perf_logs_res = (
        db.table("performance_daily_logs")
        .select("kpi_key, value")
        .eq("org_id", org_id)
        .gte("log_date", period_start)
        .execute()
    ).data or []

    # Pre-aggregate by category
    _revenue_actual     = sum(float(l.get("deal_value") or 0) for l in leads_res
                              if l.get("stage") == "converted" and not l.get("deleted_at"))
    _leads_contacted    = sum(float(l.get("value") or 0) for l in perf_logs_res
                              if l.get("kpi_key") == "Leads Contacted")
    _tickets_resolved   = sum(1 for t in tickets_res
                              if t.get("resolved_at") and not t.get("deleted_at"))
    _tasks_completed    = sum(1 for t in tasks_res
                              if t.get("status") == "completed" and not t.get("deleted_at"))
    _posts_published    = sum(float(l.get("value") or 0) for l in perf_logs_res
                              if l.get("kpi_key") == "Posts Published")
    _campaigns_launched = sum(float(l.get("value") or 0) for l in perf_logs_res
                              if l.get("kpi_key") == "Campaigns Launched")

    _CATEGORY_CURRENT = {
        "sales":     _revenue_actual,
        "leads":     _leads_contacted,
        "support":   float(_tickets_resolved),
        "tasks":     float(_tasks_completed),
        "content":   _posts_published,
        "campaigns": _campaigns_launched,
    }

    result = []
    for g in goals:
        target   = float(g.get("target_value") or 0)
        category = g.get("goal_category", "custom")
        current  = _CATEGORY_CURRENT.get(category, 0.0)
        pct      = _kpi_achievement_pct(current, target)
        result.append({
            **g,
            "current_value":    round(current, 2),
            "achievement_pct":  pct,
            "pace":             _pace_status(current, target, days_elapsed, days_in_period),
            "colour":           _score_colour(pct),
            "days_elapsed":     days_elapsed,
            "days_in_period":   days_in_period,
        })

    _cache_set(cache_key, result, _TTL_GOALS)
    return result


def upsert_business_goal(db, org_id: str, goal_data: dict, created_by: str) -> dict:
    """Create or update a business goal. Invalidates cache on write."""
    existing = (
        db.table("business_goals")
        .select("id")
        .eq("org_id", org_id)
        .eq("goal_name", goal_data["goal_name"])
        .eq("period_start", goal_data["period_start"])
        .limit(1)
        .execute()
    )
    payload = {
        "org_id": org_id,
        "goal_name":     goal_data["goal_name"],
        "goal_category": goal_data["goal_category"],
        "target_value":  goal_data["target_value"],
        "unit":          goal_data.get("unit", "count"),
        "period_type":   goal_data.get("period_type", "monthly"),
        "period_start":  goal_data["period_start"],
        "notes":         goal_data.get("notes"),
        "created_by":    created_by,
        "updated_at":    datetime.utcnow().isoformat(),
    }
    if existing.data:
        row = (
            db.table("business_goals")
            .update(payload)
            .eq("id", existing.data[0]["id"])
            .execute()
        )
    else:
        row = db.table("business_goals").insert(payload).execute()

    _cache_delete(_goals_cache_key(org_id, goal_data["period_start"]))
    _cache_delete(f"perf:owner_dash:{org_id}")
    return row.data[0] if row.data else {}


def delete_business_goal(db, org_id: str, goal_id: str, period_start: str) -> bool:
    """Soft-delete a business goal."""
    db.table("business_goals").update(
        {"is_active": False, "updated_at": datetime.utcnow().isoformat()}
    ).eq("id", goal_id).eq("org_id", org_id).execute()
    _cache_delete(_goals_cache_key(org_id, period_start))
    _cache_delete(f"perf:owner_dash:{org_id}")
    return True

# ---------------------------------------------------------------------------
# Daily Executive Brief (PERF-1D)
# ---------------------------------------------------------------------------

_TTL_BRIEF = 120  # 2 min cache


async def get_daily_brief(db, org_id: str, brief_date: Optional[date] = None) -> dict:
    """
    Assembles the owner daily executive brief.

    brief_date: the date to generate the brief for. Defaults to today.
      Passing a past date lets the owner review a previous day's snapshot.
      Revenue / pipeline figures are always month-to-date for the month
      that contains brief_date. Contractor activity logs and the cache key
      are scoped to brief_date so past days are independently cached.

    Sections:
      1. Revenue snapshot  — leads.deal_value where stage=converted, this month
      2. Sales pipeline    — leads by stage + value
      3. Sales team        — per-rep revenue, leads, conversion rate
      4. Business goals    — live progress vs targets
      5. Contractor activities — KPI actuals + blocked/in-progress tasks
      6. Issues needing owner attention — internal_issues where needs_owner_attention=true

    Confirmed columns:
      leads: org_id, stage, deal_value, assigned_to, converted_at, created_at, deleted_at
      contractor_tasks: org_id, contractor_id, task_description, due_date, owner, status
      contractor_kpi_actuals: org_id, contractor_id, month_label, month_start,
                               kpi_key, actual_value, actual_label
      internal_issues: org_id, reference, title, priority, status,
                       needs_owner_attention, deleted_at, created_at
      contractors: id, full_name, role_title, org_id
      users: id, full_name, org_id, roles(template)
    """
    # brief_date defaults to today; past dates are accepted for historical review
    today = brief_date if brief_date is not None else date.today()

    # Past-date briefs get a longer cache TTL (data won't change); today gets 2 min
    is_past = today < date.today()
    ttl = 3600 if is_past else _TTL_BRIEF  # 1 hour for past, 2 min for today

    cache_key = f"perf:brief:{org_id}:{today}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    month_start_str = str(date(today.year, today.month, 1))
    days_in_month_n = _days_in_month(date(today.year, today.month, 1))
    days_elapsed    = today.day
    days_remaining  = days_in_month_n - today.day

    # E1 — all parallel
    (
        leads_res,
        contractor_tasks_res,
        contractor_kpi_res,
        contractors_res,
        issues_res,
        users_res,
        goals_res,
        org_res,
        perf_logs_leads,
        perf_logs_posts,
        activity_logs_today,
        contractor_kpi_history_res,
        staff_targets_res,
        entity_logs_res,
    ) = await asyncio.gather(
        _async_fetch(
            db, "leads",
            "stage, deal_value, assigned_to, created_at, deleted_at",
            [("org_id", "eq", org_id), ("created_at", "gte", month_start_str)],
        ),
        _async_fetch(
            db, "contractor_tasks",
            "contractor_id, task_description, due_date, owner, status",
            [("org_id", "eq", org_id)],
        ),
        _async_fetch(
            db, "contractor_kpi_actuals",
            "contractor_id, month_label, kpi_key, actual_value, actual_label",
            [("org_id", "eq", org_id), ("month_start", "gte", month_start_str)],
        ),
        _async_fetch(
            db, "contractors",
            "id, full_name, role_title, kpi_targets, fee_structure, fee_amount, fee_currency, contract_start, contract_end",
            [("org_id", "eq", org_id)],
        ),
        _async_fetch(
            db, "internal_issues",
            "id, reference, title, priority, status, needs_owner_attention, created_at",
            [("org_id", "eq", org_id), ("needs_owner_attention", "eq", True)],
        ),
        _async_fetch(
            db, "users",
            "id, full_name, roles(template)",
            [("org_id", "eq", org_id)],
        ),
        _async_fetch(
            db, "business_goals",
            "id, goal_name, goal_category, target_value, unit, period_start, notes",
            [("org_id", "eq", org_id), ("is_active", "eq", True),
             ("period_start", "eq", month_start_str)],
        ),
        _async_fetch(
            db, "organisations",
            "id, monthly_revenue_target",
            [("id", "eq", org_id)],
        ),
        _async_fetch(
            db, "performance_daily_logs",
            "kpi_key, value",
            [("org_id", "eq", org_id), ("log_date", "gte", month_start_str),
             ("kpi_key", "eq", "Leads Contacted")],
        ),
        _async_fetch(
            db, "performance_daily_logs",
            "kpi_key, value",
            [("org_id", "eq", org_id), ("log_date", "gte", month_start_str),
             ("kpi_key", "eq", "Posts Published")],
        ),
        # Contractor daily activity logs — scoped to brief_date
        _async_fetch(
            db, "performance_daily_logs",
            "id, entity_id, log_date, kpi_label, notes, blocker_note, needs_management_attention, resolved_at, created_at",
            [("org_id", "eq", org_id), ("kpi_key", "eq", "daily_activity"),
             ("log_date", "eq", str(today))],
        ),
        # All-time contractor KPI actuals — needed for termination-risk
        # detection (consecutive off-track months) and the 3-month trend
        # shown in the Owner Dashboard KPI tracker expand panel.
        _async_fetch(
            db, "contractor_kpi_actuals",
            "contractor_id, month_label, month_start, kpi_key, actual_value",
            [("org_id", "eq", org_id)],
        ),
        # Staff KPI targets for the brief's month — drives the staff rows
        # in the Owner Dashboard KPI tracker.
        _async_fetch(
            db, "staff_kpi_targets",
            "user_id, kpi_name, target_value, actual_value, month_start",
            [("org_id", "eq", org_id), ("month_start", "eq", month_start_str)],
        ),
        # Daily logs across the brief's month, by entity — gives last-log
        # date and a running-total fallback for staff rows in the tracker.
        _async_fetch(
            db, "performance_daily_logs",
            "entity_id, entity_type, log_date, kpi_key, value",
            [("org_id", "eq", org_id), ("log_date", "gte", month_start_str)],
        ),
    )

    # ── 1. Revenue snapshot ────────────────────────────────────────────────
    active_leads    = [l for l in leads_res if not l.get("deleted_at")]
    converted       = [l for l in active_leads if l.get("stage") == "converted"]
    revenue_mtd     = sum(float(l.get("deal_value") or 0) for l in converted)

    org             = org_res[0] if org_res else {}
    rev_target      = float(org.get("monthly_revenue_target") or 0)
    rev_pct         = round(revenue_mtd / rev_target * 100, 1) if rev_target > 0 else None
    rev_pace        = _pace_status(revenue_mtd, rev_target, days_elapsed, days_in_month_n) if rev_target > 0 else None

    total_leads_cnt = len(active_leads)
    total_conv      = len(converted)
    conv_rate       = round(total_conv / total_leads_cnt * 100, 1) if total_leads_cnt > 0 else 0.0

    revenue_snapshot = {
        "revenue_mtd":     revenue_mtd,
        "revenue_target":  rev_target,
        "revenue_pct":     rev_pct,
        "revenue_pace":    rev_pace,
        "days_remaining":  days_remaining,
        "total_leads":     total_leads_cnt,
        "total_converted": total_conv,
        "conversion_rate": conv_rate,
    }

    # ── 2. Sales pipeline ──────────────────────────────────────────────────
    pipeline_by_stage: dict[str, dict] = {}
    for lead in active_leads:
        s = lead.get("stage") or "unknown"
        if s not in pipeline_by_stage:
            pipeline_by_stage[s] = {"count": 0, "value": 0.0}
        pipeline_by_stage[s]["count"] += 1
        pipeline_by_stage[s]["value"] += float(lead.get("deal_value") or 0)
    pipeline = [
        {"stage": s, "count": v["count"], "value": round(v["value"], 2)}
        for s, v in sorted(pipeline_by_stage.items())
    ]
    total_pipeline_value = sum(p["value"] for p in pipeline)

    # ── 3. Sales team ──────────────────────────────────────────────────────
    rep_leads_cnt:  dict[str, int]   = {}
    rep_conv_cnt:   dict[str, int]   = {}
    rep_revenue_m:  dict[str, float] = {}
    for lead in active_leads:
        uid = lead.get("assigned_to") or "unassigned"
        if uid == "unassigned":
            continue
        rep_leads_cnt[uid] = rep_leads_cnt.get(uid, 0) + 1
        if lead.get("stage") == "converted":
            rep_conv_cnt[uid]  = rep_conv_cnt.get(uid, 0) + 1
            rep_revenue_m[uid] = rep_revenue_m.get(uid, 0.0) + float(lead.get("deal_value") or 0)

    users_by_id = {u["id"]: u for u in users_res}
    sales_team  = []
    for uid in set(rep_leads_cnt) | set(rep_revenue_m):
        user    = users_by_id.get(uid, {})
        lc      = rep_leads_cnt.get(uid, 0)
        cc      = rep_conv_cnt.get(uid, 0)
        rv      = rep_revenue_m.get(uid, 0.0)
        cr      = round(cc / lc * 100, 1) if lc > 0 else 0.0
        sales_team.append({
            "user_id":         uid,
            "name":            user.get("full_name", "Unknown"),
            "leads":           lc,
            "converted":       cc,
            "conversion_rate": cr,
            "revenue":         round(rv, 2),
        })
    sales_team.sort(key=lambda x: x["revenue"], reverse=True)
    top_performer = sales_team[0] if sales_team else None

    # ── 4. Business goals progress ─────────────────────────────────────────
    leads_contacted_actual = sum(float(l.get("value") or 0) for l in perf_logs_leads)
    posts_published_actual = sum(float(l.get("value") or 0) for l in perf_logs_posts)
    _CATEGORY_ACTUAL: dict[str, float] = {
        "sales":     revenue_mtd,
        "leads":     leads_contacted_actual,
        "support":   0.0,
        "tasks":     0.0,
        "content":   posts_published_actual,
        "campaigns": 0.0,
    }
    goals_progress = []
    for g in goals_res:
        target  = float(g.get("target_value") or 0)
        current = _CATEGORY_ACTUAL.get(g.get("goal_category", "custom"), 0.0)
        pct     = _kpi_achievement_pct(current, target)
        goals_progress.append({
            **g,
            "current_value":   round(current, 2),
            "achievement_pct": pct,
            "pace":            _pace_status(current, target, days_elapsed, days_in_month_n),
            "colour":          _score_colour(pct),
            "days_remaining":  days_remaining,
        })

    # ── 5. Contractor activities ───────────────────────────────────────────
    contractors_by_id = {c["id"]: c for c in contractors_res}
    tasks_by_c:  dict[str, list] = {}
    kpis_by_c:   dict[str, list] = {}
    for t in contractor_tasks_res:
        tasks_by_c.setdefault(t.get("contractor_id", ""), []).append(t)
    for k in contractor_kpi_res:
        kpis_by_c.setdefault(k.get("contractor_id", ""), []).append(k)

    contractor_summaries = []
    for cid, c in contractors_by_id.items():
        tasks    = tasks_by_c.get(cid, [])
        kpis     = kpis_by_c.get(cid, [])
        blocked  = [t for t in tasks if t.get("status") == "blocked"]
        in_prog  = [t for t in tasks if t.get("status") == "in_progress"]
        done     = [t for t in tasks if t.get("status") == "done"]
        # Needs company action: blocked AND owner contains "Company"
        needs_action = [
            t for t in blocked
            if "company" in (t.get("owner") or "").lower()
        ]
        # Today's activity logs for this contractor
        todays_activities = [
            a for a in activity_logs_today
            if a.get("entity_id") == cid
        ]
        has_blocker_today = any(a.get("blocker_note") for a in todays_activities)
        flagged_activities = [a for a in todays_activities if a.get("needs_management_attention")]

        contractor_summaries.append({
            "contractor_id":       cid,
            "name":                c.get("full_name", ""),
            "role":                c.get("role_title", ""),
            "tasks_total":         len(tasks),
            "tasks_done":          len(done),
            "tasks_in_progress":   len(in_prog),
            "tasks_blocked":       len(blocked),
            "activities_today":    len(todays_activities),
            "has_blocker_today":   has_blocker_today,
            "flagged_activities":  len(flagged_activities),
            "todays_activity_summary": [
                {"type": a.get("kpi_label", ""), "notes": (a.get("notes") or "")[:100],
                 "blocker": a.get("blocker_note"), "flagged": a.get("needs_management_attention", False)}
                for a in todays_activities[:3]
            ],
            "needs_company_action": [
                {"task": t.get("task_description", ""), "due": str(t.get("due_date") or ""), "owner": t.get("owner", "")}
                for t in needs_action
            ],
            "in_progress_tasks": [
                {"task": t.get("task_description", ""), "due": str(t.get("due_date") or "")}
                for t in in_prog[:3]
            ],
            "kpi_actuals": [
                {"kpi_key": k.get("kpi_key", ""), "actual_value": float(k.get("actual_value") or 0),
                 "actual_label": k.get("actual_label", ""), "month_label": k.get("month_label", "")}
                for k in kpis
            ],
        })
    contractor_summaries.sort(key=lambda x: len(x["needs_company_action"]), reverse=True)

    # ── 6. Issues needing attention ────────────────────────────────────────
    # Source 1: internal_issues with needs_owner_attention=true
    attention_issues = [
        {"id": i["id"], "reference": i.get("reference", ""), "title": i.get("title", ""),
         "priority": i.get("priority", ""), "status": i.get("status", ""),
         "created_at": str(i.get("created_at", "")),
         "source": "issue"}
        for i in issues_res
        if i.get("status") != "resolved"
    ]
    # Source 2: contractor activity logs flagged needs_management_attention=true
    # (not yet resolved — resolved_at is null)
    for a in activity_logs_today:
        if a.get("needs_management_attention") and not a.get("resolved_at"):
            contractor = contractors_by_id.get(a.get("entity_id", ""), {})
            attention_issues.append({
                "id":              a.get("id", ""),
                "source":          "activity_log",
                "contractor_id":   a.get("entity_id", ""),
                "contractor_name": contractor.get("full_name", "Unknown"),
                "activity_type":   a.get("kpi_label", ""),
                "notes":           (a.get("notes") or "")[:200],
                "blocker_note":    a.get("blocker_note", ""),
                "log_date":        str(a.get("log_date", "")),
                "created_at":      str(a.get("created_at", "")),
                "reference":       f"ACT-{a.get('id', '')[:8].upper()}",
                "title":           f"{contractor.get('full_name', 'Contractor')} — {a.get('kpi_label', 'Activity')} flagged",
                "priority":        "high" if a.get("blocker_note") else "medium",
                "status":          "open",
            })

    # ── 7. Unified staff + contractor KPI tracker (Owner Dashboard) ───────
    staff_targets_by_user: dict[str, list] = {}
    for t in staff_targets_res:
        staff_targets_by_user.setdefault(t["user_id"], []).append(t)

    entity_logs_by_id: dict[str, list] = {}
    for log in entity_logs_res:
        entity_logs_by_id.setdefault(log.get("entity_id", ""), []).append(log)

    def _tracker_last_log_date(entity_id: str) -> str | None:
        rows = entity_logs_by_id.get(entity_id, [])
        if not rows:
            return None
        return max((l.get("log_date", "") for l in rows), default=None) or None

    def _tracker_stale_flag(last_date: str | None) -> dict | None:
        if not last_date:
            return None
        delta = (today - date.fromisoformat(last_date)).days
        if delta >= 2:
            return {"type": "stale_log", "label": "Stale log", "severity": "danger"}
        return None

    contractor_summary_by_id = {cs["contractor_id"]: cs for cs in contractor_summaries}
    contractor_kpi_history_by_id: dict[str, list] = {}
    for row in contractor_kpi_history_res:
        contractor_kpi_history_by_id.setdefault(row.get("contractor_id", ""), []).append(row)

    kpi_tracker: list[dict] = []

    # Staff rows — only included once a staff member has at least one KPI
    # target set for this month (nothing meaningful to show otherwise).
    for user in users_res:
        uid = user["id"]
        user_targets = staff_targets_by_user.get(uid)
        if not user_targets:
            continue
        primary = max(user_targets, key=lambda t: float(t.get("target_value") or 0))
        target_val = float(primary.get("target_value") or 0)
        actual_val = primary.get("actual_value")
        if actual_val is None:
            actual_val = sum(
                float(l.get("value") or 0)
                for l in entity_logs_by_id.get(uid, [])
                if l.get("kpi_key") == primary.get("kpi_name")
            )
        pct = _kpi_achievement_pct(actual_val, target_val)
        status = "on_track" if pct >= 90 else "at_risk" if pct >= 60 else "off_track"
        last_date = _tracker_last_log_date(uid)
        kpi_tracker.append({
            "entity_id":     uid,
            "type":          "staff",
            "name":          user.get("full_name", ""),
            "role":          (user.get("roles") or {}).get("template", "general_staff"),
            "status":        status,
            "pace":          _pace_status(actual_val, target_val, days_elapsed, days_in_month_n),
            "key_kpi": {
                "label":  primary.get("kpi_name", ""),
                "actual": actual_val,
                "target": target_val,
                "pct":    pct,
            },
            "last_log_date": last_date,
            "flag":          _tracker_stale_flag(last_date),
            "profile":       None,
        })

    # Contractor rows — every active contractor gets a row so the owner
    # sees who exists even before any KPI actuals have been logged.
    for c in contractors_res:
        cid = c["id"]
        c_targets = c.get("kpi_targets") or []
        history = contractor_kpi_history_by_id.get(cid, [])
        actuals_by_month: dict[str, dict] = {}
        for row in history:
            ml = row.get("month_label", "")
            actuals_by_month.setdefault(ml, {})[row.get("kpi_key", "")] = row.get("actual_value")
        risk = _contractor_risk_summary(actuals_by_month, c_targets)

        primary_kpi = c_targets[0] if c_targets else None
        key_kpi = None
        status = "pending"
        if primary_kpi:
            p_key    = primary_kpi.get("key", "")
            p_type   = primary_kpi.get("kpi_type", "manual")
            p_target = primary_kpi.get("target_value")
            current_month_label = next(
                (row.get("month_label") for row in history if row.get("month_start") == month_start_str),
                None,
            )
            p_actual = actuals_by_month.get(current_month_label, {}).get(p_key) if current_month_label else None
            status = _contractor_kpi_status(p_target, p_actual, p_type)
            key_kpi = {
                "label":  primary_kpi.get("label", p_key),
                "actual": p_actual,
                "target": p_target,
                "pct":    (_kpi_achievement_pct(p_actual, float(p_target)) if (p_target and p_actual is not None) else None),
            }

        summary   = contractor_summary_by_id.get(cid, {})
        last_date = _tracker_last_log_date(cid)
        flag = None
        if risk["at_termination_risk"]:
            flag = {"type": "termination_risk", "label": "Termination risk", "severity": "danger"}
        elif summary.get("activities_today") == 0:
            flag = {"type": "no_activity", "label": "No activity logged", "severity": "warning"}

        sorted_months = sorted(
            actuals_by_month.keys(),
            key=lambda m: int(m.replace("Month", "").strip()) if m.replace("Month", "").strip().isdigit() else 0,
        )[-3:]
        trend = []
        for m in sorted_months:
            m_actuals = actuals_by_month[m]
            pcts = [
                _kpi_achievement_pct(m_actuals.get(k.get("key", "")), float(k.get("target_value") or 0))
                for k in c_targets if k.get("target_value")
            ]
            trend.append({"month": m, "score_pct": round(sum(pcts) / len(pcts), 1) if pcts else None})

        kpi_tracker.append({
            "entity_id":     cid,
            "type":          "contractor",
            "name":          c.get("full_name", ""),
            "role":          c.get("role_title", "contractor"),
            "status":        status,
            "pace":          "Behind" if status == "off_track" else "On track" if status == "on_track" else "—",
            "key_kpi":       key_kpi,
            "last_log_date": last_date,
            "flag":          flag,
            "profile": {
                "fee_structure":  c.get("fee_structure", ""),
                "fee_amount":     c.get("fee_amount"),
                "fee_currency":   c.get("fee_currency", "NGN"),
                "contract_start": str(c.get("contract_start") or ""),
                "contract_end":   str(c.get("contract_end") or ""),
                "kpi_trend":      trend,
                "risk_summary":   risk,
                "pending_tasks":  summary.get("in_progress_tasks", []),
            },
        })

    _STATUS_SORT = {"off_track": 0, "at_risk": 1, "pending": 2, "on_track": 3}
    kpi_tracker.sort(key=lambda r: _STATUS_SORT.get(r["status"], 2))

    result = {
        "generated_at":          datetime.utcnow().isoformat(),
        "period":                f"{month_start_str} — {today}",
        "brief_date":            str(today),
        "days_elapsed":          days_elapsed,
        "days_remaining":        days_remaining,
        "revenue_snapshot":      revenue_snapshot,
        "pipeline":              pipeline,
        "total_pipeline_value":  round(total_pipeline_value, 2),
        "sales_team":            sales_team,
        "top_performer":         top_performer,
        "goals":                 goals_progress,
        "contractors":           contractor_summaries,
        "attention_issues":      attention_issues,
        "kpi_tracker":           kpi_tracker,
    }
    _cache_set(cache_key, result, ttl)
    return result


def _compute_sales_agent_kpis(db, org_id: str, user_id: str, month_str: str) -> dict:
    """
    Auto-compute sales_agent KPIs for a specific agent + month.
    Reads from leads, lead_assignments, direct_sales, performance_daily_logs.
    S14: every fetch wrapped — failure returns None for that KPI, never crashes.
    """
    m_start     = _month_start(month_str)
    m_start_str = m_start.isoformat()
    m_end_str   = date(m_start.year + (m_start.month // 12),
                       (m_start.month % 12) + 1, 1).isoformat() if m_start.month < 12 \
                  else date(m_start.year + 1, 1, 1).isoformat()

    # ── Leads assigned to this agent this month ───────────────────────────────
    try:
        leads_res = (
            db.table("leads")
            .select("id, stage, deal_value, created_at, converted_at, response_time_minutes, first_contacted_at, assigned_to")
            .eq("org_id", org_id)
            .eq("assigned_to", user_id)
            .is_("deleted_at", "null")
            .execute()
        )
        leads = leads_res.data or []
        if isinstance(leads, dict):
            leads = [leads]
    except Exception as exc:
        logger.warning("_compute_sales_agent_kpis leads fetch failed: %s", exc)
        leads = []

    # ── Lead assignments for this agent this month (Leads Contacted) ──────────
    try:
        assign_res = (
            db.table("lead_assignments")
            .select("lead_id, assigned_at")
            .eq("org_id", org_id)
            .eq("user_id", user_id)
            .gte("assigned_at", f"{m_start_str}T00:00:00+00:00")
            .lt("assigned_at", f"{m_end_str}T00:00:00+00:00")
            .execute()
        )
        assignments = assign_res.data or []
        if isinstance(assignments, dict):
            assignments = [assignments]
    except Exception as exc:
        logger.warning("_compute_sales_agent_kpis assignments fetch failed: %s", exc)
        assignments = []

    # ── Direct sales recorded by this agent this month (Upsell Rate) ─────────
    try:
        sales_res = (
            db.table("direct_sales")
            .select("id, sale_date, amount")
            .eq("org_id", org_id)
            .eq("recorded_by", user_id)
            .gte("sale_date", m_start_str)
            .lt("sale_date", m_end_str)
            .execute()
        )
        direct_sales = sales_res.data or []
        if isinstance(direct_sales, dict):
            direct_sales = [direct_sales]
    except Exception as exc:
        logger.warning("_compute_sales_agent_kpis direct_sales fetch failed: %s", exc)
        direct_sales = []

    # ── Attendance days from performance_daily_logs ───────────────────────────
    try:
        att_res = (
            db.table("performance_daily_logs")
            .select("log_date, attendance_status")
            .eq("org_id", org_id)
            .eq("entity_id", user_id)
            .eq("entity_type", "staff")
            .gte("log_date", m_start_str)
            .lt("log_date", m_end_str)
            .execute()
        )
        att_logs = att_res.data or []
        if isinstance(att_logs, dict):
            att_logs = [att_logs]
    except Exception as exc:
        logger.warning("_compute_sales_agent_kpis attendance fetch failed: %s", exc)
        att_logs = []

    # ── Compute KPIs ──────────────────────────────────────────────────────────

    # Leads Contacted — distinct leads assigned this month
    leads_contacted = len({a["lead_id"] for a in assignments})

    # Response Time — avg response_time_minutes on leads with first_contacted_at this month
    try:
        resp_times = [
            float(l["response_time_minutes"])
            for l in leads
            if l.get("response_time_minutes") is not None
            and l.get("first_contacted_at", "") >= f"{m_start_str}T00:00:00+00:00"
        ]
        response_time = round(sum(resp_times) / len(resp_times), 1) if resp_times else None
    except Exception:
        response_time = None

    # Deals Closed — leads converted this month
    converted = [
        l for l in leads
        if l.get("stage") == "converted"
        and l.get("converted_at", "") >= f"{m_start_str}T00:00:00+00:00"
    ]
    deals_closed = len(converted)

    # Conversion Rate — converted / total assigned × 100
    total_assigned = len(leads)
    conversion_rate = round(deals_closed / total_assigned * 100, 1) if total_assigned > 0 else None

    # Revenue Generated — sum of deal_value on converted leads this month
    revenue_generated = round(
        sum(float(l.get("deal_value") or 0) for l in converted), 2
    )

    # Upsell Rate — count of direct sales recorded by this agent this month
    upsell_rate = len(direct_sales)

    # Attendance Days — distinct dates with attendance_status = 'Present'
    attendance_days = len({
        l["log_date"] for l in att_logs
        if (l.get("attendance_status") or "").lower() == "present"
    })

    return {
        "Leads Contacted":   leads_contacted,
        "Response Time":     response_time,
        "Deals Closed":      deals_closed,
        "Conversion Rate":   conversion_rate,
        "Revenue Generated": revenue_generated,
        "Upsell Rate":       upsell_rate,
        "Attendance Days":   attendance_days,
    }
    """
    Auto-compute all 7 sales_lead KPIs for a given org + month.
    Called from get_staff_profile when the user's role_template is 'sales_lead'.
    S14: every fetch is wrapped — failure returns None for that KPI, never crashes.
    """
    today       = date.today()
    m_start     = _month_start(month_str)
    m_start_str = m_start.isoformat()
    days_in_m   = _days_in_month(m_start)

    # ── Fetch leads for this month ────────────────────────────────────────────
    try:
        leads_res = (
            db.table("leads")
            .select("id, stage, deal_value, assigned_to, created_at, converted_at")
            .eq("org_id", org_id)
            .gte("created_at", f"{m_start_str}T00:00:00+00:00")
            .is_("deleted_at", None)
            .execute()
        )
        leads = leads_res.data or []
        if isinstance(leads, dict):
            leads = [leads]
    except Exception as exc:
        logger.warning("_compute_sales_lead_kpis leads fetch failed: %s", exc)
        leads = []

    # ── Fetch active sales_agent users ────────────────────────────────────────
    try:
        users_res = (
            db.table("users")
            .select("id")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        # Filter to sales_agents via roles join — fetch roles separately (Pattern 33)
        all_users = users_res.data or []
        if isinstance(all_users, dict):
            all_users = [all_users]
        user_ids = [u["id"] for u in all_users]

        roles_res = (
            db.table("roles")
            .select("user_id, template")
            .in_("user_id", user_ids)
            .eq("template", "sales_agent")
            .execute()
        ) if user_ids else type("R", (), {"data": []})()
        sales_agent_ids = {r["user_id"] for r in (roles_res.data or [])}
        total_agents = len(sales_agent_ids)
    except Exception as exc:
        logger.warning("_compute_sales_lead_kpis users fetch failed: %s", exc)
        sales_agent_ids = set()
        total_agents = 0

    # ── Fetch today's activity logs for sales agents ──────────────────────────
    try:
        today_str = today.isoformat()
        activity_res = (
            db.table("activity_logs")
            .select("user_id")
            .eq("org_id", org_id)
            .eq("log_date", today_str)
            .eq("log_type", "daily")
            .execute()
        )
        activity_logs = activity_res.data or []
        if isinstance(activity_logs, dict):
            activity_logs = [activity_logs]
        logged_today = {a["user_id"] for a in activity_logs if a["user_id"] in sales_agent_ids}
        compliance = round(len(logged_today) / total_agents * 100, 1) if total_agents > 0 else None
    except Exception as exc:
        logger.warning("_compute_sales_lead_kpis activity fetch failed: %s", exc)
        compliance = None

    # ── Fetch org revenue target ──────────────────────────────────────────────
    try:
        org_res = (
            db.table("organisations")
            .select("monthly_revenue_target")
            .eq("id", org_id)
            .limit(1)
            .execute()
        )
        org_data = org_res.data or []
        if isinstance(org_data, dict):
            org_data = [org_data]
        rev_target = float((org_data[0] if org_data else {}).get("monthly_revenue_target") or 0)
    except Exception as exc:
        logger.warning("_compute_sales_lead_kpis org fetch failed: %s", exc)
        rev_target = 0.0

    # ── Compute KPIs from leads data ──────────────────────────────────────────
    converted   = [l for l in leads if l.get("stage") == "converted"]
    lost        = [l for l in leads if l.get("stage") == "lost"]
    active      = [l for l in leads if l.get("stage") not in ("converted", "lost")]

    # Team Revenue vs Target
    revenue_mtd = sum(float(l.get("deal_value") or 0) for l in converted)
    team_revenue_pct = round(revenue_mtd / rev_target * 100, 1) if rev_target > 0 else None

    # Team Conversion Rate
    total_leads = len(leads)
    team_conv_rate = round(len(converted) / total_leads * 100, 1) if total_leads > 0 else None

    # Pipeline Value — sum of deal_value on non-closed, non-lost leads
    pipeline_value = round(sum(float(l.get("deal_value") or 0) for l in active), 2)

    # Lead Distribution Rate — leads per active assigned rep this month
    rep_lead_counts: dict[str, int] = {}
    for lead in leads:
        uid = lead.get("assigned_to")
        if uid:
            rep_lead_counts[uid] = rep_lead_counts.get(uid, 0) + 1
    lead_distribution = round(
        sum(rep_lead_counts.values()) / len(rep_lead_counts), 1
    ) if rep_lead_counts else None

    # Time to Close — avg days from created_at to converted_at for closed deals
    close_times = []
    for lead in converted:
        try:
            created = datetime.fromisoformat(str(lead["created_at"]).replace("Z", "+00:00"))
            closed  = datetime.fromisoformat(str(lead["converted_at"]).replace("Z", "+00:00"))
            close_times.append((closed - created).days)
        except Exception:
            pass
    time_to_close = round(sum(close_times) / len(close_times), 1) if close_times else None

    # Win / Loss Ratio
    won_count  = len(converted)
    lost_count = len(lost)
    win_loss   = round(won_count / (won_count + lost_count) * 100, 1) if (won_count + lost_count) > 0 else None

    return {
        "Team Revenue vs Target":  team_revenue_pct,
        "Team Conversion Rate":    team_conv_rate,
        "Pipeline Value":          pipeline_value,
        "Rep Activity Compliance": compliance,
        "Lead Distribution Rate":  lead_distribution,
        "Time to Close":           time_to_close,
        "Win / Loss Ratio":        win_loss,
    }


def toggle_owner_attention(db, org_id: str, issue_id: str, value: bool) -> dict:
    """Toggle needs_owner_attention on an internal issue. Manager/owner only."""
    row = (
        db.table("internal_issues")
        .update({"needs_owner_attention": value, "updated_at": datetime.utcnow().isoformat()})
        .eq("id", issue_id)
        .eq("org_id", org_id)
        .execute()
    )
    _cache_delete(f"perf:brief:{org_id}")
    return row.data[0] if row.data else {}
