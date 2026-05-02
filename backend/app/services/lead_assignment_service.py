"""
app/services/lead_assignment_service.py
ASSIGN-1 — Auto Lead Assignment Engine.

All functions are S14 — never raise. Safe degradation on any DB failure.
If auto_assign_lead() fails for any reason, the lead is simply left unassigned
and the caller (create_lead) continues normally.

Functions:
  get_active_shift(db, org_id, now_local)     → dict | None
  get_eligible_reps(db, org_id, shift)        → list[dict]
  get_least_loaded_rep(db, org_id, reps)      → dict | None
  _write_assignment(db, org_id, lead_id, ...)
  _notify_no_reps_available(db, org_id, lead_id)
  auto_assign_lead(db, org_id, lead_id, lead_source, user_id) → str | None
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, time as dt_time
from typing import Optional

logger = logging.getLogger(__name__)

_VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
_DAY_MAP = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


# ---------------------------------------------------------------------------
# get_active_shift
# ---------------------------------------------------------------------------

def get_active_shift(db, org_id: str, now_local: datetime) -> Optional[dict]:
    """
    Return the first active shift matching the current local time and day.

    Normal shift (shift_start <= shift_end):
      Active when shift_start <= now_time < shift_end.

    Midnight-spanning shift (shift_start > shift_end):
      Active when now_time >= shift_start OR now_time < shift_end.

    S14: returns None on any failure.
    """
    try:
        result = (
            db.table("lead_assignment_shifts")
            .select("*")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        shifts = result.data or []
        if isinstance(shifts, dict):
            shifts = [shifts]

        current_day = _DAY_MAP.get(now_local.weekday(), "")
        now_time = now_local.time().replace(second=0, microsecond=0)

        for shift in shifts:
            days_active = shift.get("days_active") or []
            # Normalise — Supabase may return as list or comma-string
            if isinstance(days_active, str):
                days_active = [d.strip() for d in days_active.split(",")]

            if current_day not in days_active:
                continue

            # Parse shift times
            try:
                s_start = _parse_time(shift.get("shift_start", "00:00"))
                s_end   = _parse_time(shift.get("shift_end",   "23:59"))
            except Exception:
                continue

            if s_start <= s_end:
                # Normal shift
                if s_start <= now_time < s_end:
                    return shift
            else:
                # Midnight-spanning shift
                if now_time >= s_start or now_time < s_end:
                    return shift

        return None

    except Exception as exc:
        logger.warning("get_active_shift failed org=%s: %s", org_id, exc)
        return None


def _parse_time(t) -> dt_time:
    """Parse 'HH:MM' string or time object into datetime.time."""
    if isinstance(t, dt_time):
        return t
    if isinstance(t, str):
        parts = t.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    raise ValueError(f"Cannot parse time: {t!r}")


# ---------------------------------------------------------------------------
# get_eligible_reps
# ---------------------------------------------------------------------------

def get_eligible_reps(db, org_id: str, shift: dict) -> list[dict]:
    """
    Return eligible reps from shift["assignee_ids"]:
      - is_active = True
      - is_out_of_office = False (or column absent)

    S14: returns empty list on any failure.
    """
    try:
        assignee_ids = shift.get("assignee_ids") or []
        if isinstance(assignee_ids, str):
            # Postgres array string "{uuid1,uuid2}" → list
            assignee_ids = [
                a.strip().strip('"')
                for a in assignee_ids.strip("{}").split(",")
                if a.strip()
            ]

        if not assignee_ids:
            return []

        result = (
            db.table("users")
            .select("id, full_name, whatsapp_number, is_active, is_out_of_office")
            .eq("org_id", org_id)
            .in_("id", assignee_ids)
            .execute()
        )
        users = result.data or []
        if isinstance(users, dict):
            users = [users]

        eligible = [
            u for u in users
            if u.get("is_active") is True
            and not u.get("is_out_of_office", False)
        ]
        return eligible

    except Exception as exc:
        logger.warning("get_eligible_reps failed org=%s: %s", org_id, exc)
        return []


# ---------------------------------------------------------------------------
# get_least_loaded_rep
# ---------------------------------------------------------------------------

def get_least_loaded_rep(db, org_id: str, eligible_reps: list[dict]) -> Optional[dict]:
    """
    Return the rep from eligible_reps with the fewest currently open leads.
    Open = stage NOT IN ('converted', 'lost') AND deleted_at IS NULL.

    Ties: first in list wins (deterministic).
    Returns None if eligible_reps is empty.

    S14: returns first rep on any DB failure (best-effort).
    Pattern 33: Python-side grouping, no DB GROUP BY.
    """
    if not eligible_reps:
        return None

    try:
        rep_ids = [r["id"] for r in eligible_reps]

        result = (
            db.table("leads")
            .select("assigned_to")
            .eq("org_id", org_id)
            .in_("assigned_to", rep_ids)
            .not_.in_("stage", ["converted", "lost"])
            .is_("deleted_at", "null")
            .execute()
        )
        leads = result.data or []

        # Count open leads per rep — Python-side (Pattern 33)
        counts: dict[str, int] = {r["id"]: 0 for r in eligible_reps}
        for lead in leads:
            assigned = lead.get("assigned_to")
            if assigned in counts:
                counts[assigned] += 1

        # Return rep with lowest count; ties go to first in list
        return min(eligible_reps, key=lambda r: counts.get(r["id"], 0))

    except Exception as exc:
        logger.warning("get_least_loaded_rep failed org=%s — returning first rep: %s", org_id, exc)
        return eligible_reps[0]  # S14 best-effort fallback


# ---------------------------------------------------------------------------
# _write_assignment
# ---------------------------------------------------------------------------

def _write_assignment(
    db,
    org_id: str,
    lead_id: str,
    user_id: str,
    shift_name: str,
) -> None:
    """
    Assign lead to rep:
      - UPDATE leads.assigned_to
      - INSERT lead_timeline event
      - INSERT audit_log
      - Fire new_lead_assigned notification (inapp + whatsapp if rep has number)

    S14: never raises.
    """
    try:
        # Fetch rep name for description
        rep_result = (
            db.table("users")
            .select("full_name, whatsapp_number")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        rep_data = rep_result.data
        if isinstance(rep_data, list):
            rep_data = rep_data[0] if rep_data else {}
        rep_name = (rep_data or {}).get("full_name", "Unknown")

        # Update lead
        db.table("leads").update(
            {"assigned_to": user_id}
        ).eq("id", lead_id).eq("org_id", org_id).execute()

        now_iso = datetime.now(timezone.utc).isoformat()

        # Timeline event
        try:
            db.table("lead_timeline").insert({
                "org_id":     org_id,
                "lead_id":    lead_id,
                "event_type": "assignment",
                "actor_id":   None,  # system action — Pattern 55
                "description": (
                    f"Auto-assigned to {rep_name} "
                    f"(shift: {shift_name}, strategy: least_loaded)"
                ),
                "metadata":   {"assigned_to": user_id, "shift": shift_name},
                "created_at": now_iso,
            }).execute()
        except Exception as exc:
            logger.warning("_write_assignment: timeline failed lead=%s: %s", lead_id, exc)

        # Audit log
        try:
            db.table("audit_logs").insert({
                "org_id":        org_id,
                "user_id":       None,  # system action
                "action":        "lead.auto_assigned",
                "resource_type": "lead",
                "resource_id":   lead_id,
                "new_value":     {
                    "assigned_to": user_id,
                    "method":      "auto",
                    "shift":       shift_name,
                },
                "created_at": now_iso,
            }).execute()
        except Exception as exc:
            logger.warning("_write_assignment: audit_log failed lead=%s: %s", lead_id, exc)

        # Fetch lead details for notification body
        try:
            lead_result = (
                db.table("leads")
                .select("full_name, source")
                .eq("id", lead_id)
                .maybe_single()
                .execute()
            )
            lead_data = lead_result.data
            if isinstance(lead_data, list):
                lead_data = lead_data[0] if lead_data else {}
            lead_name   = (lead_data or {}).get("full_name", "Unknown")
            lead_source = (lead_data or {}).get("source", "unknown")
        except Exception:
            lead_name   = "Unknown"
            lead_source = "unknown"

        # In-app notification to assigned rep
        try:
            db.table("notifications").insert({
                "org_id":        org_id,
                "user_id":       user_id,
                "type":          "new_lead_assigned",
                "title":         "New lead assigned to you",
                "body":          (
                    f"A new {lead_source} lead has been assigned to you: "
                    f"{lead_name}. Check your pipeline."
                ),
                "link":          f"/leads/{lead_id}",
                "channel":       "inapp",
                "is_read":       False,
                "resource_type": "lead",
                "resource_id":   lead_id,
                "created_at":    now_iso,
            }).execute()
        except Exception as exc:
            logger.warning("_write_assignment: inapp notification failed: %s", exc)

        # WhatsApp notification to rep (if they have a whatsapp_number)
        rep_wa = (rep_data or {}).get("whatsapp_number", "").strip()
        if rep_wa:
            try:
                from app.services.whatsapp_service import _get_org_wa_credentials, _call_meta_send
                phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
                if phone_id and access_token:
                    _call_meta_send(phone_id, {
                        "messaging_product": "whatsapp",
                        "to":   rep_wa,
                        "type": "text",
                        "text": {
                            "body": (
                                f"📋 New lead assigned: {lead_name} ({lead_source}). "
                                f"Check your Opsra pipeline."
                            )
                        },
                    }, token=access_token)
            except Exception as exc:
                logger.warning("_write_assignment: WA notification failed: %s", exc)

    except Exception as exc:
        logger.warning("_write_assignment failed lead=%s: %s", lead_id, exc)


# ---------------------------------------------------------------------------
# _notify_no_reps_available
# ---------------------------------------------------------------------------

def _notify_no_reps_available(db, org_id: str, lead_id: str) -> None:
    """
    Notify all owner + ops_manager users when a lead cannot be auto-assigned.
    S14: never raises.
    """
    try:
        now_iso = datetime.now(timezone.utc).isoformat()

        # Pattern 48: join roles(template), filter in Python
        result = (
            db.table("users")
            .select("id, roles(template)")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        users = result.data or []

        admin_ids = [
            u["id"] for u in users
            if (u.get("roles") or {}).get("template", "").lower()
            in ("owner", "ops_manager")
        ]

        if not admin_ids:
            logger.warning(
                "_notify_no_reps_available: no admins found for org=%s", org_id
            )
            return

        notifications = [
            {
                "org_id":        org_id,
                "user_id":       admin_id,
                "type":          "lead_assignment_failed",
                "title":         "Lead could not be auto-assigned",
                "body":          (
                    "A new lead arrived but no eligible reps are available "
                    "for the current shift. Please assign manually."
                ),
                "link":          f"/leads/{lead_id}",
                "channel":       "inapp",
                "is_read":       False,
                "resource_type": "lead",
                "resource_id":   lead_id,
                "created_at":    now_iso,
            }
            for admin_id in admin_ids
        ]

        db.table("notifications").insert(notifications).execute()

    except Exception as exc:
        logger.warning(
            "_notify_no_reps_available failed org=%s: %s", org_id, exc
        )


# ---------------------------------------------------------------------------
# auto_assign_lead  — main orchestrator
# ---------------------------------------------------------------------------

def auto_assign_lead(
    db,
    org_id: str,
    lead_id: str,
    lead_source: str,
    user_id: Optional[str],
) -> Optional[str]:
    """
    Auto-assign a newly created lead to the correct rep based on active shift
    and the Least Loaded strategy.

    Gate checks (return None immediately if any fail):
      1. org.lead_assignment_mode != 'auto'
      2. lead.contact_type != 'sales_lead'
      3. lead_source == 'import' (or 'import_')
      4. user_id is not None AND user has sales_agent role template

    After gates pass:
      - Convert UTC now() to org timezone
      - get_active_shift() → if None → notify admins, return None
      - get_eligible_reps() → if empty → notify admins, return None
      - get_least_loaded_rep() → if None → notify admins, return None
      - _write_assignment() → return rep_id

    S14: any unexpected exception is caught — lead remains created, just unassigned.
    Returns assigned user_id or None.
    """
    try:
        # ── Gate 1: org mode ──────────────────────────────────────────────
        try:
            org_result = (
                db.table("organisations")
                .select("lead_assignment_mode, timezone")
                .eq("id", org_id)
                .maybe_single()
                .execute()
            )
            org_data = org_result.data
            if isinstance(org_data, list):
                org_data = org_data[0] if org_data else None
            org_data = org_data or {}
        except Exception as exc:
            logger.warning("auto_assign_lead: org fetch failed org=%s: %s", org_id, exc)
            return None

        if org_data.get("lead_assignment_mode", "manual") != "auto":
            return None

        # ── Gate 2: contact_type ──────────────────────────────────────────
        try:
            lead_result = (
                db.table("leads")
                .select("contact_type")
                .eq("id", lead_id)
                .maybe_single()
                .execute()
            )
            lead_data = lead_result.data
            if isinstance(lead_data, list):
                lead_data = lead_data[0] if lead_data else None
            contact_type = (lead_data or {}).get("contact_type", "sales_lead")
        except Exception:
            contact_type = "sales_lead"

        if contact_type != "sales_lead":
            return None

        # ── Gate 3: import source ─────────────────────────────────────────
        src = (lead_source or "").lower()
        if src in ("import", "import_"):
            return None

        # ── Gate 4: sales_agent self-create ──────────────────────────────
        if user_id is not None:
            try:
                user_result = (
                    db.table("users")
                    .select("roles(template)")
                    .eq("id", user_id)
                    .maybe_single()
                    .execute()
                )
                user_data = user_result.data
                if isinstance(user_data, list):
                    user_data = user_data[0] if user_data else None
                template = ((user_data or {}).get("roles") or {}).get("template", "")
                if template == "sales_agent":
                    return None
            except Exception as exc:
                logger.warning("auto_assign_lead: user fetch failed: %s", exc)

        # ── Convert UTC now to org timezone ──────────────────────────────
        org_tz_str = org_data.get("timezone") or "Africa/Lagos"
        try:
            from zoneinfo import ZoneInfo
            now_local = datetime.now(ZoneInfo(org_tz_str))
        except Exception:
            now_local = datetime.now(timezone.utc)

        # ── get_active_shift ──────────────────────────────────────────────
        shift = get_active_shift(db, org_id, now_local)
        if shift is None:
            logger.info(
                "auto_assign_lead: no active shift org=%s — lead %s unassigned",
                org_id, lead_id,
            )
            _notify_no_reps_available(db, org_id, lead_id)
            return None

        # ── get_eligible_reps ─────────────────────────────────────────────
        eligible = get_eligible_reps(db, org_id, shift)
        if not eligible:
            logger.info(
                "auto_assign_lead: no eligible reps org=%s shift=%s — lead %s unassigned",
                org_id, shift.get("shift_name"), lead_id,
            )
            _notify_no_reps_available(db, org_id, lead_id)
            return None

        # ── get_least_loaded_rep ──────────────────────────────────────────
        rep = get_least_loaded_rep(db, org_id, eligible)
        if rep is None:
            _notify_no_reps_available(db, org_id, lead_id)
            return None

        # ── Write assignment ──────────────────────────────────────────────
        _write_assignment(db, org_id, lead_id, rep["id"], shift.get("shift_name", ""))
        logger.info(
            "auto_assign_lead: lead=%s assigned to rep=%s shift=%s org=%s",
            lead_id, rep["id"], shift.get("shift_name"), org_id,
        )
        return rep["id"]

    except Exception as exc:
        # S14: never raise — lead is still created, just unassigned
        logger.warning(
            "auto_assign_lead: unexpected error org=%s lead=%s — %s",
            org_id, lead_id, exc,
        )
        return None
