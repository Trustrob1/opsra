"""
app/services/account_entitlement_service.py
---------------------------------------------
ACCOUNT-PLANS AP-1 - which plan (Capture / Convert / Grow) an ORGANISATION has, which features that switches on, and
how much capped usage is left. The account-level twin of site_entitlement_service (which stays the answer for a site).

It reuses the site code for everything that is the same: the tier definitions in Settings (get_config), the date
rules (effective_status) and what a row grants (_row_grant). Only the thing a plan belongs to is different: an
organisation instead of a site.

Where the tier definitions live: Settings > Pricing on the organisation that owns the site settings (env
PLATFORM_ORG_ID, otherwise the first site_builder_settings row). One price per tier for sites and accounts (Trust, 19 Oct).

THE SAFETY SWITCH. organisations.plans_enforced defaults to false. While it is false the business behaves exactly as
it always has: every account feature is ON, nothing is counted, no row can switch anything off. A superadmin switches
it on per business. Only then do the plan rows decide. Any error while LOOKING UP the switch counts as "not enforced"
(never lock a business out because of a lookup problem); any error while working out an enforced plan means OFF (S14).

Scopes (site_feature_registry.scope_of): "site" features need a website, "account" features belong to the
organisation, "both" work either way.
  * Site context (a site_id is given): a site tier OR the owner's enforced account plan switches a feature on.
    The "everything is on while not enforced" rule is NOT applied here, so a client's site is never given features
    for free just because its workspace organisation has no plan.
  * Pure account context (no site_id): not enforced -> on; enforced -> the plan decides.

Everything is scoped by org_id (S14 / Pattern 28).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import site_entitlement_service as ent
from app.services import site_feature_registry as reg

logger = logging.getLogger(__name__)

LIVE_STATES = ent.LIVE_STATES
EntitlementError = ent.EntitlementError
EntitlementNotFound = ent.EntitlementNotFound
SOURCES = ("staff", "grandfathered")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).astimezone(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


# ---------------------------------------------------------------------------
# Tier definitions and the enforcement switch
# ---------------------------------------------------------------------------

def platform_org_id(db: Any) -> Optional[str]:
    """The organisation whose Settings hold the tier definitions: env PLATFORM_ORG_ID, else the first
    site_builder_settings row. None if neither exists."""
    env = os.getenv("PLATFORM_ORG_ID", "").strip()
    if env:
        return env
    try:
        row = _one((db.table("site_builder_settings").select("org_id").order("created_at").limit(1).execute()).data)
        return (row or {}).get("org_id")
    except Exception as exc:
        logger.warning("account_entitlement.platform_org_id failed: %s", exc)
        return None


def plan_config(db: Any) -> dict:
    """{'tiers': {...}, 'addons': {...}, 'billing': {...}} exactly as the site code reads Settings."""
    org = platform_org_id(db)
    settings = ent._settings(db, org) if org else {}
    return ent.get_config(settings)


def is_enforced(db: Any, org_id: str) -> bool:
    """True only if this business has been switched on. Any lookup problem means False (never lock anyone out)."""
    try:
        row = _one((db.table("organisations").select("plans_enforced").eq("id", org_id).limit(1).execute()).data)
        return bool(row and row.get("plans_enforced") is True)
    except Exception as exc:
        logger.warning("account_entitlement.is_enforced failed org=%s: %s", org_id, exc)
        return False


# ---------------------------------------------------------------------------
# Working out what an organisation has
# ---------------------------------------------------------------------------

def _compute(db: Any, org_id: str, now: datetime) -> dict:
    cfg = plan_config(db)
    rows = (db.table("org_plans").select("*").eq("org_id", org_id).neq("status", "cancelled").execute()).data or []
    features: set = set()
    caps: dict = {}
    out_rows = []
    for r in rows:
        eff = ent.effective_status(r, cfg, now)
        out_rows.append({**r, "effective_status": eff})
        if eff in LIVE_STATES:
            f, c = ent._row_grant(r, cfg)
            features |= f
            for ck, cv in c.items():
                caps[ck] = caps.get(ck, 0) + cv
    return {"cfg": cfg, "rows": out_rows, "features": features, "caps": caps}


def _usage(db: Any, org_id: str, now: datetime) -> dict:
    ps = ent.period_start(now).isoformat()
    rows = (db.table("org_usage_counters").select("*").eq("org_id", org_id).eq("period_start", ps).execute()).data or []
    return {r["cap_key"]: int(r.get("used") or 0) for r in rows}


def get_entitlements(db: Any, org_id: str, now: Optional[datetime] = None) -> dict:
    """Everything a screen needs about one organisation. Raises on a database error (callers that must not fail
    use has_feature / consume instead)."""
    now = now or _now()
    c = _compute(db, org_id, now)
    used = _usage(db, org_id, now)
    cfg = c["cfg"]
    tier_row = next((r for r in c["rows"] if r["kind"] == "tier"), None)
    monthly = {k: {"used": used.get(k, 0), "cap": c["caps"].get(k, 0)} for k, m in reg.CAPS.items() if m == "monthly"}
    return {
        "org_id": org_id,
        "enforced": is_enforced(db, org_id),
        "tier": ({
            "key": tier_row["key"], "label": (cfg["tiers"].get(tier_row["key"]) or {}).get("label", tier_row["key"]),
            "status": tier_row["effective_status"], "source": tier_row.get("source"),
            "paid_until": tier_row.get("paid_until"), "id": tier_row.get("id"),
            "picks": (tier_row.get("config") or {}).get("picks") or [],
        } if tier_row else None),
        "addons": [{"id": r.get("id"), "key": r["key"], "status": r["effective_status"], "source": r.get("source"),
                    "paid_until": r.get("paid_until")} for r in c["rows"] if r["kind"] == "addon"],
        "features": sorted(c["features"]),
        "caps": c["caps"],
        "usage": monthly,
    }


def _plan_has(db: Any, org_id: str, key: str, now: datetime) -> bool:
    return key in _compute(db, org_id, now)["features"]


def has_feature(db: Any, key: str, *, org_id: str, site_id: Optional[str] = None, site_org_id: Optional[str] = None,
                now: Optional[datetime] = None) -> bool:
    """Is this feature on? See the module notes for the site / account rules. Never raises; fails closed."""
    try:
        if not reg.is_feature(key) or not org_id:
            return False
        now = now or _now()
        scope = reg.scope_of(key)
        if site_id:
            owner = site_org_id or org_id
            if scope in ("site", "both") and ent.has_feature(db, owner, site_id, key, now):
                return True
            # the owner's enforced account plan covers its own sites (decision D-1)
            return bool(is_enforced(db, owner) and _plan_has(db, owner, key, now))
        if scope == "site":
            return False                      # needs a website
        if not is_enforced(db, org_id):
            return True                       # unchanged behaviour until switched on
        return _plan_has(db, org_id, key, now)
    except Exception as exc:  # S14 - fail closed
        logger.warning("account_entitlement.has_feature failed org=%s key=%s: %s", org_id, key, exc)
        return False


def consume(db: Any, key: str, *, org_id: str, n: int = 1, now: Optional[datetime] = None) -> bool:
    """Use n units of the monthly cap behind a feature. Not enforced -> allowed and NOT counted (as today).
    Enforced -> feature must be on and a cap must exist (a missing cap means no allowance); the count moves with a
    conditional update so two requests at once can never both squeeze under the cap. Never raises; fails closed."""
    try:
        if not reg.is_feature(key) or not org_id or not isinstance(n, int) or n < 0:
            return False
        now = now or _now()
        if not is_enforced(db, org_id):
            return True
        c = _compute(db, org_id, now)
        if key not in c["features"]:
            return False
        cap_key = reg.cap_for_feature(key)
        if cap_key is None or reg.CAPS.get(cap_key) != "monthly":
            return True
        cap = c["caps"].get(cap_key, 0)
        if cap <= 0:
            return False
        if n == 0:
            return True
        ps = ent.period_start(now).isoformat()
        for _ in range(3):
            row = _one((db.table("org_usage_counters").select("*").eq("org_id", org_id).eq("cap_key", cap_key)
                        .eq("period_start", ps).limit(1).execute()).data)
            if row is None:
                try:
                    db.table("org_usage_counters").insert({"org_id": org_id, "cap_key": cap_key, "period_start": ps,
                                                           "used": 0, "updated_at": _iso(now)}).execute()
                except Exception:       # a parallel request created it first; read it again
                    pass
                continue
            used = int(row.get("used") or 0)
            if used + n > cap:
                return False
            res = (db.table("org_usage_counters").update({"used": used + n, "updated_at": _iso(now)})
                   .eq("id", row["id"]).eq("used", used).execute())
            if res.data:
                return True
        return False
    except Exception as exc:  # S14 - fail closed
        logger.warning("account_entitlement.consume failed org=%s key=%s: %s", org_id, key, exc)
        return False


# ---------------------------------------------------------------------------
# Staff actions
# ---------------------------------------------------------------------------

def _log_event(db: Any, org_id: str, actor: str, event: str, detail: dict) -> None:
    try:
        db.table("org_plan_events").insert({"org_id": org_id, "actor": actor, "event": event, "detail": detail}).execute()
    except Exception as exc:
        logger.warning("org_plan_events insert failed org=%s event=%s: %s", org_id, event, exc)


def _org_exists(db: Any, org_id: str) -> dict:
    row = _one((db.table("organisations").select("id, subscription_status").eq("id", org_id).limit(1).execute()).data)
    if not row:
        raise EntitlementNotFound("Organisation not found")
    return row


def grant(db: Any, org_id: str, actor: str, kind: str, key: str, *, until: Optional[datetime] = None,
          source: str = "staff", picks: Optional[list] = None, now: Optional[datetime] = None) -> dict:
    """Staff switch a tier or add-on on for an organisation with no payment. source is 'staff' or 'grandfathered'.
    `until` None = no end date. An organisation has one tier: granting a different tier replaces the current one."""
    now = now or _now()
    if kind not in ("tier", "addon"):
        raise EntitlementError("Choose a tier or an add-on.")
    if source not in SOURCES:
        raise EntitlementError("Source must be staff or grandfathered.")
    org = _org_exists(db, org_id)
    if (org.get("subscription_status") or "") == "site_workspace":
        raise EntitlementError("A client's website workspace has no account plan. Give the site a tier instead.")
    cfg = plan_config(db)
    defs = cfg["tiers"] if kind == "tier" else cfg["addons"]
    if key not in defs:
        raise EntitlementError("Unknown tier." if kind == "tier" else "Unknown add-on.")
    if until is not None:
        until = ent._parse(until)
        if until is None or until <= now:
            raise EntitlementError("The end date must be in the future.")
    config: dict = {}
    if kind == "tier":
        config["picks"] = ent._clean_picks(defs[key], picks)
    fields = {"status": "active", "source": source, "paid_until": _iso(until) if until else None,
              "grace_until": None, "next_reminder_at": None, "config": config, "updated_at": _iso(now)}
    q = db.table("org_plans").select("*").eq("org_id", org_id).eq("kind", kind).neq("status", "cancelled")
    if kind == "addon":
        q = q.eq("key", key)
    existing = _one(q.limit(1).execute().data)
    if existing:
        db.table("org_plans").update({**fields, "key": key}).eq("id", existing["id"]).eq("org_id", org_id).execute()
        event = "plan_changed"
    else:
        db.table("org_plans").insert({"org_id": org_id, "kind": kind, "key": key, "price_ngn": 0,
                                      "created_by": None, "created_at": _iso(now), **fields}).execute()
        event = "plan_granted"
    _log_event(db, org_id, actor, event, {"kind": kind, "key": key, "source": source, "until": fields["paid_until"],
                                          "picks": config.get("picks")})
    return get_entitlements(db, org_id, now)


def set_status(db: Any, org_id: str, plan_id: str, action: str, actor: str, *, until: Optional[datetime] = None,
               now: Optional[datetime] = None) -> dict:
    """pause (active/grace -> paused), resume (paused -> active, optional new end date), cancel (any -> cancelled).
    Conditional updates, so a double click or a parallel worker run changes nothing twice."""
    now = now or _now()
    if action not in ("pause", "resume", "cancel"):
        raise EntitlementError("Unknown action.")
    row = _one((db.table("org_plans").select("*").eq("id", plan_id).eq("org_id", org_id).limit(1).execute()).data)
    if not row:
        raise EntitlementNotFound("Plan not found")
    if action == "pause":
        res = (db.table("org_plans").update({"status": "paused", "updated_at": _iso(now)})
               .eq("id", plan_id).eq("org_id", org_id).in_("status", ["active", "grace"]).execute())
    elif action == "resume":
        patch: dict = {"status": "active", "grace_until": None, "updated_at": _iso(now)}
        if until is not None:
            until = ent._parse(until)
            if until is None or until <= now:
                raise EntitlementError("The end date must be in the future.")
            patch["paid_until"] = _iso(until)
        res = (db.table("org_plans").update(patch).eq("id", plan_id).eq("org_id", org_id).eq("status", "paused").execute())
    else:
        res = (db.table("org_plans").update({"status": "cancelled", "updated_at": _iso(now)})
               .eq("id", plan_id).eq("org_id", org_id).in_("status", ["pending", "active", "grace", "paused"]).execute())
    if not res.data:
        raise EntitlementError("That can't be done in its current state.")
    _log_event(db, org_id, actor, f"plan_{action}", {"plan_id": plan_id, "key": row.get("key")})
    return get_entitlements(db, org_id, now)


def set_enforced(db: Any, org_id: str, flag: bool, actor: str) -> dict:
    """Switch plan enforcement on or off for one business."""
    org = _org_exists(db, org_id)
    if (org.get("subscription_status") or "") == "site_workspace":
        raise EntitlementError("A client's website workspace is not billed as an account.")
    db.table("organisations").update({"plans_enforced": bool(flag)}).eq("id", org_id).execute()
    _log_event(db, org_id, actor, "enforcement_on" if flag else "enforcement_off", {})
    return get_entitlements(db, org_id)


def overview(db: Any, now: Optional[datetime] = None) -> dict:
    """Superadmin list: every business (site workspaces left out) with its plan, status and enforcement."""
    now = now or _now()
    cfg = plan_config(db)
    orgs = (db.table("organisations").select("id, name, slug, subscription_status, subscription_tier, plans_enforced")
            .neq("subscription_status", "site_workspace").limit(1000).execute()).data or []
    plans = (db.table("org_plans").select("*").neq("status", "cancelled").limit(5000).execute()).data or []
    by_org: dict = {}
    for p in plans:
        by_org.setdefault(p["org_id"], []).append(p)
    out, value, enforced = [], 0, 0
    for o in orgs:
        rows = by_org.get(o["id"], [])
        tier = next((r for r in rows if r["kind"] == "tier"), None)
        eff = ent.effective_status(tier, cfg, now) if tier else None
        addons = [r["key"] for r in rows if r["kind"] == "addon"]
        if o.get("plans_enforced"):
            enforced += 1
        if tier and eff in LIVE_STATES and tier.get("source") == "paid":
            value += int((cfg["tiers"].get(tier["key"]) or {}).get("monthly_ngn") or 0)
        out.append({"org_id": o["id"], "name": o.get("name"), "slug": o.get("slug"),
                    "enforced": bool(o.get("plans_enforced")),
                    "tier": tier["key"] if tier else None, "status": eff, "source": tier.get("source") if tier else None,
                    "paid_until": tier.get("paid_until") if tier else None, "plan_id": tier.get("id") if tier else None,
                    "addons": addons})
    return {"orgs": out, "totals": {"businesses": len(out), "enforced": enforced, "monthly_value_ngn": value}}
