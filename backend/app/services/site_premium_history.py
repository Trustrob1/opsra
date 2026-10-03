"""
app/services/site_premium_history.py
-------------------------------------
SITE-PREMIUM P4-4 - a Premium customer manages the versions of their own design (buttons only).

  * History: the last versions of the design, newest first, each with a plain label of what changed ("Brand colour,
    fonts changed"). One tap restores any of them. Restoring only moves the pointer to a version that already exists,
    so it never costs an edit and nothing is lost: the version being replaced stays in the history.
  * Try another design: Claude designs a completely new look from the same content and photos (the only part of
    P4 that uses API credit). It is generated into a HELD-BACK slot (kind 'redesign', staged = true): the live site
    is not touched until the customer presses Keep. Discard throws it away. A redesign is counted when it was made
    successfully (it cost money), whether or not it is kept; a failed attempt is never counted.
  * Allowance: site_builder_settings.site_premium_redesigns_included (default 2 per site, DP spec 'one generation plus
    two redesigns'). After go-live a redesign is a paid add-on (price open, DP-2), so it is refused unless
    site_builder_settings.site_premium_post_live_redesign is on. The payment itself belongs to P5.

Customers only ever pass a design id that belongs to their own site; every query is scoped by org and site.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.services import site_premium_generation_service as gen
from app.services import site_premium_service as premium
from app.services.site_ops_service import Conflict, NotFound, SiteOpsError, ValidationFailed

logger = logging.getLogger(__name__)

HISTORY_SHOWN = 10
DEFAULT_REDESIGNS_INCLUDED = 2
LIVE_STATUSES = ("live", "renewal_due", "lapsed")
RECENT_FAILURE_HOURS = 2
USED_EVENT = "premium_redesign_used"


class RedesignNotAllowed(SiteOpsError):
    status_code = 402
    code = "REDESIGN_NOT_INCLUDED"


def _one(data):
    return (data or [None])[0]


# ------------------------------------------------------------------ history

def change_label(row: dict) -> str:
    """A plain label for one saved version."""
    kind = row.get("kind")
    if kind == "generate":
        return "First design"
    if kind == "redesign":
        return "New design"
    if kind == "import":
        return "Imported design"
    changes = (((row.get("checks") or {}).get("tweak") or {}).get("changes")) or {}
    parts: list[str] = []
    if "accent" in changes:
        parts.append("brand colour")
    if "headline_font" in changes or "body_font" in changes:
        parts.append("fonts")
    if changes.get("sections"):
        parts.append("section colours")
    layout = changes.get("layout") or {}
    if any(c.get("show") is False for c in layout.values()):
        parts.append("a section hidden")
    if any(c.get("show") is True for c in layout.values()):
        parts.append("a section shown")
    if any("size" in c for c in layout.values()):
        parts.append("heading size")
    if not parts:
        return "Look changed"
    text = ", ".join(parts) + " changed"
    return text[:1].upper() + text[1:]


def history(db: Any, org_id: str, site: dict) -> list[dict]:
    """The customer's saved versions, newest first (held-back redesigns are not shown here)."""
    rows = (db.table("site_designs").select("id, version, kind, created_at, checks, staged")
            .eq("site_id", site["id"]).eq("org_id", org_id).eq("status", "ready").order("version", desc=True)
            .limit(HISTORY_SHOWN + 5).execute()).data or []
    rows = [r for r in rows if not r.get("staged")][:HISTORY_SHOWN]
    current = site.get("current_design_id")
    return [{"id": r["id"], "version": r["version"], "kind": r["kind"], "label": change_label(r),
             "created_at": r.get("created_at"), "is_current": r["id"] == current, "can_restore": r["id"] != current}
            for r in rows]


def restore(db: Any, org_id: str, site: dict, design_id: str) -> dict:
    """Make a saved version current again. Never counts as an edit. Raises NotFound / ValidationFailed."""
    if (site.get("tier") or "standard") != "premium":
        raise NotFound("This site does not have a Premium design.")
    row = _one((db.table("site_designs").select("id, version, staged").eq("id", design_id).eq("site_id", site["id"])
                .eq("org_id", org_id).eq("status", "ready").limit(1).execute()).data)
    if not row or row.get("staged"):
        raise NotFound("That version was not found.")
    if row["id"] == site.get("current_design_id"):
        raise ValidationFailed("That is already your current design.")
    return premium.use_design(db, org_id, site, design_id)


def version_preview(db: Any, org_id: str, site: dict, design_id: str, assets_by_id: dict) -> str:
    """The page for one saved version with the site's current content. Held-back redesigns use redesign_preview."""
    row = _one((db.table("site_designs").select("id, staged").eq("id", design_id).eq("site_id", site["id"])
                .eq("org_id", org_id).eq("status", "ready").limit(1).execute()).data)
    if not row or row.get("staged"):
        raise NotFound("That version was not found.")
    return premium.preview_design(db, org_id, site, design_id, assets_by_id)


# ------------------------------------------------------------------ try another design

def _used(db: Any, org_id: str, site_id: str) -> int:
    """New designs made from the free included allowance (a design bought as a paid credit is not counted here)."""
    rows = (db.table("site_events").select("id, detail").eq("org_id", org_id).eq("site_id", site_id).eq("event", USED_EVENT)
            .execute()).data or []
    return sum(1 for r in rows if not (r.get("detail") or {}).get("paid_credit"))


def free_available(db: Any, org_id: str, site: dict, settings: dict) -> dict:
    """Whether an included (free) new design can be made now. After go-live nothing is free: a new design is a paid add-on."""
    included = settings.get("site_premium_redesigns_included")
    included = DEFAULT_REDESIGNS_INCLUDED if included is None else int(included)
    used = _used(db, org_id, site["id"])
    live = (site.get("status") or "") in LIVE_STATUSES
    return {"included": included, "used": used, "live": live, "free_ok": (not live) and used < included}


def _staged_row(db: Any, org_id: str, site_id: str) -> Optional[dict]:
    return _one((db.table("site_designs").select("id, version, created_at, checks").eq("site_id", site_id).eq("org_id", org_id)
                 .eq("kind", "redesign").eq("status", "ready").eq("staged", True).order("version", desc=True).limit(1)
                 .execute()).data)


def redesign_status(db: Any, org_id: str, site: dict) -> dict:
    """Everything the 'Try another design' card needs. Never raises for a normal Premium site."""
    from app.services import site_premium_billing_service as billing
    settings = gen.settings_for(db, org_id)
    fa = free_available(db, org_id, site, settings)
    included, used, live = fa["included"], fa["used"], fa["live"]
    cfg = billing.get_config(settings)
    credits = billing.redesign_credits(db, org_id, site["id"])
    override = live and bool(settings.get("site_premium_post_live_redesign")) and used < included   # staff switch: free for this org
    allowed = fa["free_ok"] or credits["available"] > 0 or override
    price = cfg["redesign_fee_ngn"]
    reason = None
    if not allowed:
        if live:
            reason = "A new design after your site is live is a paid add-on" + (f" ({billing._money(price)})." if price > 0 else ". Ask us and we will set it up.")
        else:
            reason = "Your included new designs are used." + (f" You can buy another for {billing._money(price)}." if price > 0 else " Ask us if you would like another one.")
    gen.sweep_stale(db, org_id, site["id"])
    running = _one((db.table("site_designs").select("id, created_at").eq("site_id", site["id"]).eq("org_id", org_id)
                    .eq("kind", "redesign").in_("status", ["generating", "checking"]).order("version", desc=True)
                    .limit(1).execute()).data)
    staged = _staged_row(db, org_id, site["id"])
    failed = None
    if not running and not staged:
        last = _one((db.table("site_designs").select("id, status, checks, created_at").eq("site_id", site["id"])
                     .eq("org_id", org_id).eq("kind", "redesign").order("version", desc=True).limit(1).execute()).data)
        if last and last.get("status") == "failed" and _recent(last.get("created_at")):
            failed = ((last.get("checks") or {}).get("errors") or ["The new design could not be finished."])[0]
    return {"allowed": allowed, "blocked_reason": reason, "included": included, "used": used,
            "remaining": max(included - used, 0), "can_buy": (not allowed) and price > 0, "price": price,
            "credits": credits["available"], "uses_free": fa["free_ok"], "in_progress": running, "staged": _public_staged(staged), "last_failure": failed,
            "counts_as_edit": False}


def _public_staged(staged: Optional[dict]) -> Optional[dict]:
    """The held-back design as the customer sees it: no raw checks, only the plain carried-over sentence."""
    if not staged:
        return None
    from app.services import site_premium_carry
    out = {k: v for k, v in staged.items() if k != "checks"}
    out["carried_note"] = site_premium_carry.carried_note((staged.get("checks") or {}).get("carried"))
    return out


def _recent(created_at: Optional[str]) -> bool:
    try:
        when = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - when < timedelta(hours=RECENT_FAILURE_HOURS)
    except Exception:  # S14
        return False


def start_redesign(db: Any, org_id: str, site: dict, actor: str) -> dict:
    """Guards, then the 'generating' row (kind redesign). The caller queues the worker with the returned id."""
    if (site.get("tier") or "standard") != "premium" or not site.get("current_design_id"):
        raise ValidationFailed("Only a site with a Premium design can try another design.")
    status = redesign_status(db, org_id, site)
    if status["staged"]:
        raise Conflict("You already have a new design waiting. Keep it or discard it first.")
    if not status["allowed"]:
        raise RedesignNotAllowed(status["blocked_reason"])
    return gen.start_generation(db, org_id, site, actor, kind="redesign")


def redesign_preview(db: Any, org_id: str, site: dict, assets_by_id: dict) -> str:
    row = _staged_row(db, org_id, site["id"])
    if not row:
        raise NotFound("There is no new design waiting.")
    return premium.preview_design(db, org_id, site, row["id"], assets_by_id)


def keep_redesign(db: Any, org_id: str, site: dict) -> dict:
    """Make the held-back design the live one. The design it replaces stays in the history."""
    row = _staged_row(db, org_id, site["id"])
    if not row:
        raise NotFound("There is no new design waiting.")
    db.table("site_designs").update({"staged": False}).eq("id", row["id"]).eq("org_id", org_id).execute()
    db.table("sites").update({"tier": "premium", "current_design_id": row["id"],
                              "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", site["id"]).eq("org_id", org_id).execute()
    premium._prune(db, org_id, site["id"], keep_id=row["id"])
    return row


def discard_redesign(db: Any, org_id: str, site: dict) -> None:
    """Throw the held-back design away. It stays counted as used, because it was made."""
    row = _staged_row(db, org_id, site["id"])
    if not row:
        raise NotFound("There is no new design waiting.")
    db.table("site_designs").delete().eq("id", row["id"]).eq("org_id", org_id).execute()
