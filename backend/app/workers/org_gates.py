# app/utils/org_gates.py
# 9E-D — Business Logic Gates
# Utility functions for subscription gating, quiet hours, and daily message limits.
# S14: has_exceeded_daily_limit returns False (allow send) on any exception —
#      never block on a config error.

from datetime import datetime, timezone, time as dt_time
import logging

logger = logging.getLogger(__name__)

# ── D3 constants ──────────────────────────────────────────────────────────────

DEFAULT_DAILY_CUSTOMER_LIMIT = 3
SYSTEM_DAILY_CUSTOMER_CEILING = 20   # hardcoded — cannot be exceeded by any org


# ── D1 — Subscription status gating ──────────────────────────────────────────

def is_org_active(org: dict) -> bool:
    """
    Returns True if org is in a state that allows automated messaging.
    "active" and "grace" both proceed.
    "read_only", "suspended", null, or any other value → False.
    """
    status = (org.get("subscription_status") or "").lower()
    return status in ("active", "grace")


def is_org_processable(org: dict) -> bool:
    """
    Stricter gate — returns True only for "active".
    Use for workers that must not run during grace period.
    """
    status = (org.get("subscription_status") or "").lower()
    return status == "active"


# ── D2 — Quiet hours enforcement ──────────────────────────────────────────────

def is_quiet_hours(org: dict, now_utc: datetime) -> bool:
    """
    Returns True if the current time (in the org's timezone) falls inside
    the org's configured quiet hours window.

    Returns False if:
      - org has no quiet_hours_start or quiet_hours_end configured
      - timezone conversion fails (safe fallback — never block on config error)
      - any other exception occurs

    Args:
        org:     Organisation dict — must contain timezone, quiet_hours_start,
                 quiet_hours_end keys (all nullable).
        now_utc: Current UTC datetime (timezone-aware or naive — both handled).
    """
    quiet_start = org.get("quiet_hours_start")
    quiet_end   = org.get("quiet_hours_end")

    if not quiet_start or not quiet_end:
        return False

    try:
        import pytz

        tz_name = org.get("timezone") or "Africa/Lagos"
        tz = pytz.timezone(tz_name)

        # Ensure now_utc is timezone-aware
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        local_now = now_utc.astimezone(tz)
        local_time = local_now.time().replace(second=0, microsecond=0)

        # Parse HH:MM or HH:MM:SS strings (DB stores as time type → HH:MM:SS)
        start_parts = quiet_start.split(":")
        end_parts   = quiet_end.split(":")
        start_h, start_m = int(start_parts[0]), int(start_parts[1])
        end_h,   end_m   = int(end_parts[0]),   int(end_parts[1])
        start = dt_time(start_h, start_m)
        end   = dt_time(end_h,   end_m)

        # Handle overnight windows e.g. 22:00 → 06:00
        if start <= end:
            return start <= local_time < end
        else:
            # Crosses midnight
            return local_time >= start or local_time < end

    except Exception as exc:
        logger.warning("is_quiet_hours failed — defaulting to False: %s", exc)
        return False


def get_quiet_hours_end_utc(org: dict, now_utc: datetime) -> datetime:
    """
    Returns the next quiet hours end time as a UTC datetime.
    Used to set whatsapp_messages.send_after when holding a message.
    Falls back to now_utc + 8 hours if anything fails.
    """
    try:
        import pytz
        from datetime import timedelta

        tz_name   = org.get("timezone") or "Africa/Lagos"
        quiet_end = org.get("quiet_hours_end")

        if not quiet_end:
            return now_utc

        tz = pytz.timezone(tz_name)

        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        local_now = now_utc.astimezone(tz)
        end_parts    = quiet_end.split(":")
        end_h, end_m = int(end_parts[0]), int(end_parts[1])

        # Build today's quiet-end in local time
        end_local = local_now.replace(
            hour=end_h, minute=end_m, second=0, microsecond=0
        )

        # If end time has already passed today, move to tomorrow
        if end_local <= local_now:
            end_local = end_local + __import__("datetime").timedelta(days=1)

        return end_local.astimezone(pytz.utc).replace(tzinfo=None)

    except Exception as exc:
        logger.warning("get_quiet_hours_end_utc failed — using fallback: %s", exc)
        from datetime import timedelta
        return now_utc + timedelta(hours=8)


# ── D3 — Daily customer message limit ────────────────────────────────────────

def get_daily_customer_limit(org: dict) -> int:
    """
    Returns the effective daily message limit for a customer in this org.
    Hierarchy: system ceiling → org-configured value → default fallback (3).
    The system ceiling of 20 can never be exceeded regardless of org config.
    """
    configured = org.get("daily_customer_message_limit")
    if configured is None:
        return DEFAULT_DAILY_CUSTOMER_LIMIT
    return min(int(configured), SYSTEM_DAILY_CUSTOMER_CEILING)


def has_exceeded_daily_limit(db, org_id: str, customer_id: str, limit: int) -> bool:
    """
    Returns True if this customer has already received >= limit messages today (UTC).
    Counts rows in whatsapp_messages for this customer in the current UTC day.

    S14: Returns False on any exception — a config/DB error must never block sending.

    Args:
        db:          Supabase client
        org_id:      Organisation UUID
        customer_id: Customer UUID
        limit:       Effective daily limit (from get_daily_customer_limit)
    """
    try:
        from datetime import date
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        result = (
            db.table("whatsapp_messages")
            .select("id", count="exact")
            .eq("org_id", org_id)
            .eq("customer_id", customer_id)
            .gte("created_at", today_start)
            .execute()
        )
        count = result.count if result.count is not None else len(result.data or [])
        return count >= limit

    except Exception as exc:
        logger.warning(
            "has_exceeded_daily_limit check failed for customer %s — allowing send: %s",
            customer_id, exc,
        )
        return False  # S14 — never block on error
