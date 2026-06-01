"""
app/routers/performance_logs.py
CPM-1B — Daily Performance Tracking

8 routes (Pattern 53 — static before parameterised):
  POST /performance-logs/generate-token/{contractor_id}
  GET  /performance-logs/public/{token}
  POST /performance-logs/public/{token}
  GET  /performance-logs/{contractor_id}/summary
  GET  /performance-logs/{contractor_id}
  POST /performance-logs/{contractor_id}
  PATCH /performance-logs/{contractor_id}/{log_id}
  DELETE /performance-logs/{contractor_id}/{log_id}

Patterns applied:
  Pattern 11: JWT from Zustand — never localStorage
  Pattern 12: org_id from JWT only — never from payload
  Pattern 33: no .ilike() — Python-side filtering only
  Pattern 53: static routes before parameterised
  Pattern 62: db via Depends(get_supabase)
  S1:  org_id from JWT only
  S3:  Pydantic field constraints
  S14: per-record try/except in worker
  Public routes: PIN-gated, no JWT
  PIN: bcrypt hash — never stored plaintext
  Brute-force protection: Redis, 5 attempts, 15-min lockout (fail open)
"""
from __future__ import annotations

import logging
import secrets
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Lazy imports for optional dependencies (fail open)
# ---------------------------------------------------------------------------

def _get_bcrypt():
    try:
        import bcrypt as _bcrypt
        return _bcrypt
    except ImportError:
        pass
    try:
        from passlib.hash import bcrypt as _passlib_bcrypt
        class _Compat:
            @staticmethod
            def hashpw(pw: bytes, salt: bytes) -> bytes:
                return _passlib_bcrypt.hash(pw.decode()).encode()
            @staticmethod
            def gensalt() -> bytes:
                return b""  # passlib handles internally
            @staticmethod
            def checkpw(pw: bytes, hashed: bytes) -> bool:
                return _passlib_bcrypt.verify(pw.decode(), hashed.decode())
        return _Compat()
    except ImportError:
        return None


def _get_redis():
    try:
        import os, redis as _redis
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return None
        return _redis.from_url(url, socket_connect_timeout=2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_current_org(db, token: str):
    """Decode JWT Bearer token and return org dict. Raises 401 on failure."""
    from app.dependencies import get_current_org as _gco
    # Re-use existing dependency by calling it directly with the token
    # This is called manually in public routes where Depends() is not used.
    raise NotImplementedError("Use Depends(get_current_org) in JWT routes")


# Import the standard org dependency used across the codebase
from app.dependencies import get_current_org

MANAGER_ROLES = {"owner", "ops_manager"}


def _require_manager(org: dict):
    role = (org.get("roles") or {}).get("template", "")
    if role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Manager access required")


# ---------------------------------------------------------------------------
# PIN helpers
# ---------------------------------------------------------------------------

def _generate_log_token() -> str:
    return secrets.token_hex(32)  # 64-char hex


def _hash_pin(pin: str) -> str:
    bcrypt = _get_bcrypt()
    if bcrypt is None:
        raise HTTPException(status_code=500, detail="bcrypt not available")
    hashed = bcrypt.hashpw(pin.encode(), bcrypt.gensalt())
    return hashed.decode() if isinstance(hashed, bytes) else hashed


def _verify_pin(pin: str, hashed: str) -> bool:
    bcrypt = _get_bcrypt()
    if bcrypt is None:
        return False
    try:
        return bcrypt.checkpw(pin.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Brute-force protection (fail open — never block on Redis unavailability)
# ---------------------------------------------------------------------------

_PIN_MAX_ATTEMPTS = 5
_PIN_LOCKOUT_SECONDS = 900  # 15 minutes


def _pin_lockout_key(token: str) -> str:
    return f"pin_lockout:{token}"


def _pin_attempts_key(token: str) -> str:
    return f"pin_attempts:{token}"


def _check_and_record_pin_failure(token: str) -> int:
    """Returns remaining attempts. 0 means locked. -1 means Redis unavailable (fail open)."""
    try:
        r = _get_redis()
        if r is None:
            return -1
        lock_key = _pin_lockout_key(token)
        if r.exists(lock_key):
            return 0
        attempts_key = _pin_attempts_key(token)
        attempts = r.incr(attempts_key)
        if attempts == 1:
            r.expire(attempts_key, _PIN_LOCKOUT_SECONDS)
        if attempts >= _PIN_MAX_ATTEMPTS:
            r.setex(lock_key, _PIN_LOCKOUT_SECONDS, "1")
            r.delete(attempts_key)
            return 0
        return _PIN_MAX_ATTEMPTS - attempts
    except Exception as exc:
        logger.warning("Redis PIN protection unavailable (fail open): %s", exc)
        return -1  # fail open


def _clear_pin_attempts(token: str):
    try:
        r = _get_redis()
        if r is None:
            return
        r.delete(_pin_attempts_key(token))
        r.delete(_pin_lockout_key(token))
    except Exception:
        pass


def _is_pin_locked(token: str) -> bool:
    try:
        r = _get_redis()
        if r is None:
            return False
        return bool(r.exists(_pin_lockout_key(token)))
    except Exception:
        return False  # fail open


# ---------------------------------------------------------------------------
# Pace calculation
# ---------------------------------------------------------------------------

def _pace_status(progress_pct: float, days_elapsed: int, total_days: int) -> str:
    if days_elapsed == 0:
        return "pending"
    expected_pct = (days_elapsed / total_days) * 100
    ratio = progress_pct / expected_pct if expected_pct > 0 else 0
    if ratio >= 0.9:
        return "on_track"
    if ratio >= 0.65:
        return "at_risk"
    return "off_track"


def _compute_summary(contractor: dict, logs: list, ref_date: date) -> dict:
    """Compute running totals, pace, weekly breakdown for a given month.
    Month boundaries are relative to contract_start, not calendar months.
    e.g. if contract_start = 2026-04-15, Month 1 = Apr 15 – May 14,
    Month 2 = May 15 – Jun 14, etc.
    """
    # Determine contract_start — fall back to calendar month if not set
    contract_start_str = contractor.get("contract_start")
    if contract_start_str:
        try:
            contract_start = date.fromisoformat(contract_start_str)
        except ValueError:
            contract_start = None
    else:
        contract_start = None

    if contract_start:
        # How many full 30-day periods have elapsed since contract_start?
        days_since_start = (ref_date - contract_start).days
        if days_since_start < 0:
            # ref_date is before contract start — nothing to show
            period_index = 0
        else:
            period_index = days_since_start // 30  # 0-based month index

        month_start = contract_start + timedelta(days=period_index * 30)
        month_end = contract_start + timedelta(days=(period_index + 1) * 30 - 1)
        total_days = 30
        days_elapsed = min((ref_date - month_start).days + 1, total_days)
        days_remaining = max(total_days - days_elapsed, 0)
        month_label = f"Month {period_index + 1} ({month_start.strftime('%b %d')} – {month_end.strftime('%b %d, %Y')})"
    else:
        # Fallback: calendar month
        month_start = date(ref_date.year, ref_date.month, 1)
        total_days = monthrange(ref_date.year, ref_date.month)[1]
        month_end = date(ref_date.year, ref_date.month, total_days)
        days_elapsed = min((ref_date - month_start).days + 1, total_days)
        days_remaining = max(total_days - days_elapsed, 0)
        month_label = ref_date.strftime("%B %Y")

    kpi_targets = contractor.get("kpi_targets") or []

    # Index logs by kpi_key
    logs_by_kpi: dict[str, list] = {}
    for log in logs:
        k = log["kpi_key"]
        if k not in logs_by_kpi:
            logs_by_kpi[k] = []
        logs_by_kpi[k].append(log)

    kpi_summaries = []
    for kpi in kpi_targets:
        key = kpi.get("key", "")
        kpi_logs = logs_by_kpi.get(key, [])
        target_value = kpi.get("target_value") or 0

        # Running total — sum of numeric values this month
        running_total = sum(
            float(l["value"]) for l in kpi_logs if l.get("value") is not None
        )
        progress_pct = (running_total / target_value * 100) if target_value else 0
        pace_projected = (
            (running_total / days_elapsed) * total_days if days_elapsed > 0 else 0
        )
        pace_st = _pace_status(progress_pct, days_elapsed, total_days)

        # Weekly breakdown — relative to month_start (contract-relative, not calendar day)
        weekly: dict[int, dict] = {w: {"week": w, "total": 0.0, "days_logged": 0} for w in range(1, 5)}
        for log in kpi_logs:
            try:
                ld = date.fromisoformat(log["log_date"])
                # Day number relative to contract month start (day 1 = first day of this contract month)
                day_in_month = (ld - month_start).days + 1
                week_num = min(((day_in_month - 1) // 7) + 1, 4)
                weekly[week_num]["total"] += float(log["value"] or 0)
                weekly[week_num]["days_logged"] += 1
            except Exception:
                pass

        # Daily entries
        daily_entries = [
            {
                "log_date": l["log_date"],
                "value": l.get("value"),
                "label_value": l.get("label_value"),
                "notes": l.get("notes"),
            }
            for l in sorted(kpi_logs, key=lambda x: x.get("log_date", ""))
        ]

        kpi_summaries.append({
            "kpi_key": key,
            "kpi_label": kpi.get("label", key),
            "kpi_type": kpi.get("kpi_type", "manual"),
            "target_value": target_value,
            "target_label": kpi.get("target_label"),
            "running_total": round(running_total, 4),
            "progress_pct": round(progress_pct, 2),
            "pace_projected": round(pace_projected, 4),
            "pace_status": pace_st,
            "weekly_breakdown": list(weekly.values()),
            "daily_entries": daily_entries,
        })

    return {
        "contractor_id": contractor["id"],
        "month_label": month_label,
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "kpi_summaries": kpi_summaries,
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GenerateTokenRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=6, pattern=r"^\d{4,6}$")
    log_retention_months: Optional[int] = Field(default=6, ge=1, le=24)
    regenerate_token: Optional[bool] = False


class DailyLogEntry(BaseModel):
    kpi_key: str = Field(..., max_length=100)
    kpi_label: Optional[str] = Field(default=None, max_length=255)
    value: Optional[float] = None
    label_value: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)


class DailyLogCreate(BaseModel):
    kpi_key: str = Field(..., max_length=100)
    kpi_label: Optional[str] = Field(default=None, max_length=255)
    log_date: str = Field(..., max_length=10)  # ISO date
    value: Optional[float] = None
    label_value: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)


class DailyLogUpdate(BaseModel):
    value: Optional[float] = None
    label_value: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)


class PublicLogSubmit(BaseModel):
    pin: str = Field(..., min_length=4, max_length=6)
    log_date: str = Field(..., max_length=10)
    entries: List[DailyLogEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contractor_or_404(db, contractor_id: str, org_id: str) -> dict:
    res = (
        db.table("contractors")
        .select("*")
        .eq("id", contractor_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return res.data[0]


def _log_or_404(db, log_id: str, contractor_id: str, org_id: str) -> dict:
    res = (
        db.table("performance_daily_logs")
        .select("*")
        .eq("id", log_id)
        .eq("entity_id", contractor_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return res.data[0]


def _upsert_log(db, org_id: str, contractor_id: str, entry: dict, logged_via: str = "direct", token: str = None) -> dict:
    """Upsert a single daily log row. Unique on (entity_id, kpi_key, log_date)."""
    now = datetime.utcnow().isoformat()
    payload = {
        "org_id": org_id,
        "entity_type": "contractor",
        "entity_id": contractor_id,
        "kpi_key": entry["kpi_key"],
        "kpi_label": entry.get("kpi_label"),
        "log_date": entry["log_date"],
        "value": entry.get("value"),
        "label_value": entry.get("label_value"),
        "notes": entry.get("notes"),
        "logged_via": logged_via,
        "logged_by_token": token,
        "updated_at": now,
    }
    # Check for existing row
    existing = (
        db.table("performance_daily_logs")
        .select("id")
        .eq("entity_id", contractor_id)
        .eq("kpi_key", entry["kpi_key"])
        .eq("log_date", entry["log_date"])
        .limit(1)
        .execute()
    )
    if existing.data:
        row_id = existing.data[0]["id"]
        upd = {k: v for k, v in payload.items() if k not in ("org_id", "entity_type", "entity_id", "kpi_key", "log_date")}
        res = (
            db.table("performance_daily_logs")
            .update(upd)
            .eq("id", row_id)
            .execute()
        )
    else:
        payload["created_at"] = now
        res = db.table("performance_daily_logs").insert(payload).execute()

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to save log entry")
    return res.data[0]


# ---------------------------------------------------------------------------
# Routes — Pattern 53: static before parameterised
# ---------------------------------------------------------------------------

# ── 1. POST /performance-logs/generate-token/{contractor_id} ─────────────────

@router.post(
    "/performance-logs/generate-token/{contractor_id}",
    status_code=status.HTTP_200_OK,
    tags=["performance-logs"],
)
def generate_log_token(
    contractor_id: str,
    body: GenerateTokenRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    org_id = org["org_id"]
    contractor = _contractor_or_404(db, contractor_id, org_id)

    # Regenerate or keep existing token
    if body.regenerate_token or not contractor.get("log_token"):
        new_token = _generate_log_token()
    else:
        new_token = contractor["log_token"]

    pin_hash = _hash_pin(body.pin)

    db.table("contractors").update({
        "log_token": new_token,
        "log_pin": pin_hash,
        "log_retention_months": body.log_retention_months,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", contractor_id).execute()

    import os
    frontend_url = os.environ.get("FRONTEND_URL", "https://app.opsra.io").rstrip("/")
    log_url = f"{frontend_url}/log/{new_token}"

    return {
        "status": "ok",
        "data": {
            "log_token": new_token,
            "log_url": log_url,
            "log_retention_months": body.log_retention_months,
        },
    }


# ── 2. GET /performance-logs/public/{token} ───────────────────────────────────
# Public route — no JWT. Returns contractor name + KPI targets only.

@router.get(
    "/performance-logs/public/{token}",
    status_code=status.HTTP_200_OK,
    tags=["performance-logs"],
)
def get_public_log_form(token: str, db=Depends(get_supabase)):
    if len(token) != 64:
        raise HTTPException(status_code=404, detail="Invalid log link")

    res = (
        db.table("contractors")
        .select("id, full_name, role_title, kpi_targets, contract_start, contract_end, log_token, log_pin, log_retention_months")
        .eq("log_token", token)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Log link not found or expired")

    contractor = res.data[0]

    # Gap 3: check contract_end — reject submissions after contract has ended
    contract_end = contractor.get("contract_end")
    if contract_end:
        try:
            from datetime import date as _date
            if _date.today() > _date.fromisoformat(contract_end):
                raise HTTPException(
                    status_code=403,
                    detail="This contract has ended. Log submissions are no longer accepted.",
                )
        except HTTPException:
            raise
        except Exception:
            pass  # fail open — never block on date parse error

    # Never return log_pin (hash) in any response
    # Fetch current + overdue tasks for the contractor
    today_str = date.today().isoformat()
    # Fetch all non-done tasks — filter current/overdue Python-side (Pattern 33)
    tasks_res = (
        db.table("contractor_tasks")
        .select("id, task_description, phase, week_number, due_date, status, owner, notes")
        .eq("contractor_id", contractor["id"])
        .neq("status", "done")
        .order("due_date", desc=False)
        .execute()
    )
    all_tasks = tasks_res.data or []
    # Keep tasks due within the next 7 days, overdue, or with no due date
    from datetime import timedelta
    lookahead_str = (date.today() + timedelta(days=7)).isoformat()
    tasks = [
        t for t in all_tasks
        if not t.get("due_date") or t["due_date"] <= lookahead_str
    ]

    return {
        "status": "ok",
        "data": {
            "contractor_id": contractor["id"],
            "full_name": contractor["full_name"],
            "role_title": contractor["role_title"],
            "kpi_targets": contractor.get("kpi_targets") or [],
            "tasks": tasks,
        },
    }


# ── 3. POST /performance-logs/public/{token} ─────────────────────────────────
# Public route — no JWT. PIN-gated daily log submission.

@router.post(
    "/performance-logs/public/{token}",
    status_code=status.HTTP_201_CREATED,
    tags=["performance-logs"],
)
def submit_public_log(token: str, body: PublicLogSubmit, db=Depends(get_supabase)):
    if len(token) != 64:
        raise HTTPException(status_code=404, detail="Invalid log link")

    # Check lockout first (fail open)
    if _is_pin_locked(token):
        raise HTTPException(
            status_code=429,
            detail="Too many incorrect PIN attempts. Please try again in 15 minutes.",
        )

    res = (
        db.table("contractors")
        .select("id, org_id, full_name, kpi_targets, log_token, log_pin")
        .eq("log_token", token)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Log link not found or expired")

    contractor = res.data[0]

    # Gap 3: check contract_end — reject submissions after contract has ended
    contract_end_str = contractor.get("contract_end")
    if contract_end_str:
        try:
            from datetime import date as _date
            if _date.today() > _date.fromisoformat(contract_end_str):
                raise HTTPException(
                    status_code=403,
                    detail="This contract has ended. Log submissions are no longer accepted.",
                )
        except HTTPException:
            raise
        except Exception:
            pass  # fail open

    pin_hash = contractor.get("log_pin") or ""

    if not pin_hash:
        raise HTTPException(status_code=403, detail="Log link not configured — contact your manager")

    if not _verify_pin(body.pin, pin_hash):
        remaining = _check_and_record_pin_failure(token)
        if remaining == 0:
            raise HTTPException(
                status_code=429,
                detail="Too many incorrect PIN attempts. Please try again in 15 minutes.",
            )
        msg = "Incorrect PIN."
        if remaining > 0:
            msg += f" {remaining} attempt{'s' if remaining != 1 else ''} remaining."
        raise HTTPException(status_code=403, detail=msg)

    # PIN correct — clear any partial failure count
    _clear_pin_attempts(token)

    org_id = contractor["org_id"]
    contractor_id = contractor["id"]
    saved = []
    for entry in body.entries:
        try:
            row = _upsert_log(
                db, org_id, contractor_id,
                {**entry.model_dump(), "log_date": body.log_date},
                logged_via="public_link",
                token=token,
            )
            saved.append(row["id"])
        except Exception as exc:
            logger.error("Failed to save public log entry kpi=%s: %s", entry.kpi_key, exc)

    return {
        "status": "ok",
        "data": {
            "saved": len(saved),
            "contractor_name": contractor["full_name"],
            "log_date": body.log_date,
        },
    }


# ── 4. GET /performance-logs/{contractor_id}/summary ─────────────────────────
# Must be declared before GET /{contractor_id} (Pattern 53)

@router.get(
    "/performance-logs/{contractor_id}/summary",
    status_code=status.HTTP_200_OK,
    tags=["performance-logs"],
)
def get_performance_summary(
    contractor_id: str,
    month: Optional[str] = None,  # ISO date — defaults to current month
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    org_id = org["org_id"]
    contractor = _contractor_or_404(db, contractor_id, org_id)

    if month:
        try:
            ref_date = date.fromisoformat(month)
        except ValueError:
            raise HTTPException(status_code=422, detail="month must be an ISO date (YYYY-MM-DD)")
    else:
        ref_date = date.today()

    # Compute contract-relative month boundaries for the log fetch
    contract_start_str = contractor.get("contract_start")
    if contract_start_str:
        try:
            contract_start = date.fromisoformat(contract_start_str)
            days_since_start = (ref_date - contract_start).days
            period_index = max(days_since_start, 0) // 30
            month_start = contract_start + timedelta(days=period_index * 30)
            month_end = contract_start + timedelta(days=(period_index + 1) * 30 - 1)
        except ValueError:
            month_start = date(ref_date.year, ref_date.month, 1)
            month_end = date(ref_date.year, ref_date.month, monthrange(ref_date.year, ref_date.month)[1])
    else:
        month_start = date(ref_date.year, ref_date.month, 1)
        month_end = date(ref_date.year, ref_date.month, monthrange(ref_date.year, ref_date.month)[1])

    logs_res = (
        db.table("performance_daily_logs")
        .select("*")
        .eq("entity_id", contractor_id)
        .eq("org_id", org_id)
        .gte("log_date", month_start.isoformat())
        .lte("log_date", month_end.isoformat())
        .execute()
    )
    logs = logs_res.data or []

    summary = _compute_summary(contractor, logs, ref_date)
    return {"status": "ok", "data": summary}


# ── 5. GET /performance-logs/{contractor_id} ─────────────────────────────────

@router.get(
    "/performance-logs/{contractor_id}",
    status_code=status.HTTP_200_OK,
    tags=["performance-logs"],
)
def list_performance_logs(
    contractor_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    org_id = org["org_id"]
    _contractor_or_404(db, contractor_id, org_id)

    query = (
        db.table("performance_daily_logs")
        .select("*")
        .eq("entity_id", contractor_id)
        .eq("org_id", org_id)
        .order("log_date", desc=True)
    )
    if date_from:
        query = query.gte("log_date", date_from)
    if date_to:
        query = query.lte("log_date", date_to)

    res = query.execute()
    items = res.data or []
    return {"status": "ok", "data": {"items": items, "total": len(items)}}


# ── 6. POST /performance-logs/{contractor_id} ────────────────────────────────

@router.post(
    "/performance-logs/{contractor_id}",
    status_code=status.HTTP_201_CREATED,
    tags=["performance-logs"],
)
def log_daily_entry(
    contractor_id: str,
    body: DailyLogCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    org_id = org["org_id"]
    _contractor_or_404(db, contractor_id, org_id)

    row = _upsert_log(db, org_id, contractor_id, body.model_dump(), logged_via="direct")
    return {"status": "ok", "data": row}


# ── 7. PATCH /performance-logs/{contractor_id}/{log_id} ──────────────────────

@router.patch(
    "/performance-logs/{contractor_id}/{log_id}",
    status_code=status.HTTP_200_OK,
    tags=["performance-logs"],
)
def update_daily_log(
    contractor_id: str,
    log_id: str,
    body: DailyLogUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    org_id = org["org_id"]
    _log_or_404(db, log_id, contractor_id, org_id)

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.utcnow().isoformat()

    res = (
        db.table("performance_daily_logs")
        .update(updates)
        .eq("id", log_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Update failed")
    return {"status": "ok", "data": res.data[0]}


# ── 8. DELETE /performance-logs/{contractor_id}/{log_id} ─────────────────────

@router.delete(
    "/performance-logs/{contractor_id}/{log_id}",
    status_code=status.HTTP_200_OK,
    tags=["performance-logs"],
)
def delete_daily_log(
    contractor_id: str,
    log_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    org_id = org["org_id"]
    _log_or_404(db, log_id, contractor_id, org_id)

    db.table("performance_daily_logs").delete().eq("id", log_id).execute()
    return {"status": "ok", "data": {"deleted": True}}
