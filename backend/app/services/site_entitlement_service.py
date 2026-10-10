"""
app/services/site_entitlement_service.py
------------------------------------------
SITE-ADDONS A0-1 - which tier a site has, which features that switches on, and how much capped usage is left.

The ONE place that answers "is feature X on for this site?" is has_feature(). Every later automation (instant reply,
scoring, sequences, reports) asks it before it runs, so a downgrade, pause or unpaid renewal takes effect without
touching the published page.

What a site has lives in public.site_addons (one tier row, plus optional add-on rows). Which features a tier or add-on
includes, its price, setup fee and caps live in Settings (site_builder_settings.pricing["tiers"] / ["addons"] /
["tier_billing"]); the feature KEYS live in site_feature_registry.py. All prices default to 0 = "not for sale yet";
staff can still grant a tier at price 0 (that is how Trust's own sites and tests are switched on).

Status rules (effective_status): the stored status is kept in step by the billing worker (A0-2), but this module also
works the status out from the dates, so a late worker can never leave a lapsed site switched on.
  pending / paused / cancelled           -> features off
  active, paid_until in the future       -> on
  paid_until passed, inside grace        -> on ("grace"; default 7 days)
  paid_until passed, grace over          -> off ("paused"); the site and its data are kept
  staff-granted with no paid_until       -> on until a staff member changes it
  paid-source row with no paid_until     -> off (nothing was ever paid)

Safety: has_feature() and consume() never raise (S14) and FAIL CLOSED: on any error the answer is "off". Money and
cost limits are never decided by the browser; caps come from Settings on the server.

Everything is scoped by org_id (S14 / Pattern 28).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.services import site_feature_registry as reg

logger = logging.getLogger(__name__)

LAGOS = timezone(timedelta(hours=1))
LIVE_STATES = ("active", "grace")
BILLING_DEFAULTS = {"period_days": 30, "grace_days": 7, "reminder_days": [5, 1]}


class EntitlementError(Exception):
    status_code = 422
    code = "VALIDATION_ERROR"


class EntitlementNotFound(EntitlementError):
    status_code = 404
    code = "NOT_FOUND"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).astimezone(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _int(value, default: int, low: int = 0, high: Optional[int] = None) -> int:
    if isinstance(value, bool):
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < low or (high is not None and n > high):
        return default
    return n


def _settings(db: Any, org_id: str) -> dict:
    return _one((db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data) or {}


def period_start(now: Optional[datetime] = None) -> date:
    """First day of the current month in Lagos time. Monthly caps reset then."""
    local = (now or _now()).astimezone(LAGOS)
    return date(local.year, local.month, 1)


# ---------------------------------------------------------------------------
# Settings -> config
# ---------------------------------------------------------------------------

def _features(value, default: list) -> list:
    if not isinstance(value, list):
        return list(default)
    seen: list = []
    for k in value:
        if reg.is_feature(k) and k not in seen:
            seen.append(k)
    return seen


def _caps(value) -> dict:
    out: dict = {}
    if isinstance(value, dict):
        for k in reg.CAPS:
            if k in value:
                n = _int(value[k], -1, 0)
                if n >= 0:
                    out[k] = n
    return out


def _pick_one(value, default: list) -> list:
    if not isinstance(value, list):
        return [list(g) for g in default]
    groups = []
    for g in value:
        if isinstance(g, list):
            keys = [k for k in g if reg.is_feature(k)]
            if len(keys) >= 2:
                groups.append(keys)
    return groups


def get_config(settings: Optional[dict]) -> dict:
    """pricing.tiers / addons / tier_billing merged over the approved defaults. Bad values fall back to defaults."""
    pricing = (settings or {}).get("pricing")
    pricing = pricing if isinstance(pricing, dict) else {}
    tiers_raw = pricing.get("tiers") if isinstance(pricing.get("tiers"), dict) else {}
    addons_raw = pricing.get("addons") if isinstance(pricing.get("addons"), dict) else {}
    bill_raw = pricing.get("tier_billing") if isinstance(pricing.get("tier_billing"), dict) else {}

    tiers: dict = {}
    for key in reg.TIER_KEYS:
        raw = tiers_raw.get(key) if isinstance(tiers_raw.get(key), dict) else {}
        monthly = _int(raw.get("monthly_ngn"), 0, 0)
        tiers[key] = {
            "key": key,
            "label": (str(raw.get("label")).strip() if isinstance(raw.get("label"), str) and raw.get("label").strip()
                      else reg.DEFAULT_LABELS[key]),
            "monthly_ngn": monthly,
            "setup_fee_ngn": _int(raw.get("setup_fee_ngn"), 0, 0),
            "features": _features(raw.get("features"), reg.DEFAULT_TIER_FEATURES[key]),
            "pick_one": _pick_one(raw.get("pick_one"), reg.DEFAULT_PICK_ONE[key]),
            "caps": _caps(raw.get("caps")),
            "sellable": monthly > 0,
        }
    addons: dict = {}
    for key in reg.ADDON_KEYS:
        raw = addons_raw.get(key) if isinstance(addons_raw.get(key), dict) else {}
        monthly = _int(raw.get("monthly_ngn"), 0, 0)
        caps = _caps(raw.get("caps")) if "caps" in raw else dict(reg.DEFAULT_ADDON_CAPS.get(key, {}))
        addons[key] = {
            "key": key,
            "label": (str(raw.get("label")).strip() if isinstance(raw.get("label"), str) and raw.get("label").strip()
                      else reg.DEFAULT_ADDON_LABELS[key]),
            "monthly_ngn": monthly,
            "features": _features(raw.get("features"), [key]),
            "caps": caps,
            "sellable": monthly > 0,
        }
    rd = bill_raw.get("reminder_days")
    reminder_days = ([n for n in (_int(x, -1, 0, 60) for x in rd) if n >= 0] if isinstance(rd, list) else None)
    billing = {
        "period_days": _int(bill_raw.get("period_days"), BILLING_DEFAULTS["period_days"], 1, 366),
        "grace_days": _int(bill_raw.get("grace_days"), BILLING_DEFAULTS["grace_days"], 0, 60),
        "reminder_days": reminder_days if reminder_days else list(BILLING_DEFAULTS["reminder_days"]),
    }
    return {"tiers": tiers, "addons": addons, "billing": billing}


# whole-number limits for the PATCH /sites/settings check (same style as builder_access)
_PRICE_MAX = 100_000_000


def validate_pricing(pricing) -> None:
    """Rejects a nonsense tiers / addons / tier_billing block with a plain message. Normalises numbers to ints in place.
    Raises EntitlementError (the router turns it into a 422). Blocks that are absent are left alone."""
    if not isinstance(pricing, dict):
        return

    def whole(v, low, high, label):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not (low <= int(v) <= high):
            raise EntitlementError(f"{label} must be a whole number from {low:,} to {high:,}.")
        return int(v)

    def check_item(item, label, tier: bool):
        if not isinstance(item, dict):
            raise EntitlementError(f"{label} settings must be a set of values.")
        for f, lab in (("monthly_ngn", "monthly price"), ("setup_fee_ngn", "set-up fee")):
            if f in item:
                item[f] = whole(item[f], 0, _PRICE_MAX, f"{label} {lab}")
        if "label" in item and not (isinstance(item["label"], str) and 0 < len(item["label"].strip()) <= 40):
            raise EntitlementError(f"{label} name must be 1 to 40 characters.")
        if "features" in item:
            if not isinstance(item["features"], list) or any(not reg.is_feature(k) for k in item["features"]):
                raise EntitlementError(f"{label} has a feature that Opsra doesn't know.")
        if "caps" in item:
            if not isinstance(item["caps"], dict):
                raise EntitlementError(f"{label} limits must be a set of numbers.")
            for ck, cv in item["caps"].items():
                if ck not in reg.CAPS:
                    raise EntitlementError(f"{label} has a limit that Opsra doesn't know.")
                item["caps"][ck] = whole(cv, 0, 100_000_000, f"{label} limit")
        if tier and "pick_one" in item:
            pk = item["pick_one"]
            if not isinstance(pk, list) or any(not isinstance(g, list) or any(not reg.is_feature(k) for k in g) for g in pk):
                raise EntitlementError(f"{label} choose-one groups are not valid.")

    if "tiers" in pricing:
        t = pricing["tiers"]
        if not isinstance(t, dict) or any(k not in reg.TIER_KEYS for k in t):
            raise EntitlementError("Tier settings must use the tiers Capture, Convert and Grow.")
        for k, v in t.items():
            check_item(v, reg.DEFAULT_LABELS[k], True)
    if "addons" in pricing:
        a = pricing["addons"]
        if not isinstance(a, dict) or any(k not in reg.ADDON_KEYS for k in a):
            raise EntitlementError("Add-on settings contain an add-on that Opsra doesn't know.")
        for k, v in a.items():
            check_item(v, reg.DEFAULT_ADDON_LABELS[k], False)
    if "tier_billing" in pricing:
        b = pricing["tier_billing"]
        if not isinstance(b, dict):
            raise EntitlementError("Tier billing settings must be a set of numbers.")
        if "period_days" in b:
            b["period_days"] = whole(b["period_days"], 1, 366, "Billing period (days)")
        if "grace_days" in b:
            b["grace_days"] = whole(b["grace_days"], 0, 60, "Grace period (days)")
        if "reminder_days" in b:
            rd = b["reminder_days"]
            if not isinstance(rd, list) or len(rd) > 5:
                raise EntitlementError("Reminder days must be a short list of whole numbers.")
            b["reminder_days"] = [whole(x, 0, 60, "Reminder day") for x in rd]


# ---------------------------------------------------------------------------
# Status and entitlement maths
# ---------------------------------------------------------------------------

def effective_status(row: dict, cfg: dict, now: datetime) -> str:
    st = row.get("status")
    if st in ("pending", "paused", "cancelled"):
        return st
    paid_until = _parse(row.get("paid_until"))
    if paid_until is None:
        return "active" if row.get("source") == "staff" else "pending"
    if now <= paid_until:
        return "active"
    grace_end = _parse(row.get("grace_until")) or (paid_until + timedelta(days=cfg["billing"]["grace_days"]))
    return "grace" if now <= grace_end else "paused"


def _row_grant(row: dict, cfg: dict) -> tuple:
    """(features, caps) one row switches on, from Settings. An unknown key switches on nothing."""
    if row.get("kind") == "tier":
        d = cfg["tiers"].get(row.get("key"))
        if not d:
            return set(), {}
        feats = set(d["features"])
        picks = (row.get("config") or {}).get("picks") or []
        for group in d["pick_one"]:
            chosen = [p for p in picks if p in group]
            if chosen:
                feats.add(chosen[0])
        return feats, dict(d["caps"])
    d = cfg["addons"].get(row.get("key"))
    if not d:
        return set(), {}
    return set(d["features"]), dict(d["caps"])


def _compute(db: Any, org_id: str, site_id: str, now: datetime) -> dict:
    cfg = get_config(_settings(db, org_id))
    rows = (db.table("site_addons").select("*").eq("org_id", org_id).eq("site_id", site_id)
            .neq("status", "cancelled").execute()).data or []
    features: set = set()
    caps: dict = {}
    out_rows = []
    for r in rows:
        eff = effective_status(r, cfg, now)
        out_rows.append({**r, "effective_status": eff})
        if eff in LIVE_STATES:
            f, c = _row_grant(r, cfg)
            features |= f
            for ck, cv in c.items():
                caps[ck] = caps.get(ck, 0) + cv
    return {"cfg": cfg, "rows": out_rows, "features": features, "caps": caps}


def _usage(db: Any, org_id: str, site_id: str, now: datetime) -> dict:
    ps = period_start(now).isoformat()
    rows = (db.table("site_usage_counters").select("*").eq("org_id", org_id).eq("site_id", site_id)
            .eq("period_start", ps).execute()).data or []
    return {r["cap_key"]: int(r.get("used") or 0) for r in rows}


def get_entitlements(db: Any, org_id: str, site_id: str, now: Optional[datetime] = None) -> dict:
    """Everything a screen or automation needs about one site. Raises on a database error (callers that must not
    fail use has_feature / consume instead)."""
    now = now or _now()
    c = _compute(db, org_id, site_id, now)
    used = _usage(db, org_id, site_id, now)
    tier_row = next((r for r in c["rows"] if r["kind"] == "tier"), None)
    cfg = c["cfg"]
    monthly = {k: {"used": used.get(k, 0), "cap": c["caps"].get(k, 0)} for k, m in reg.CAPS.items() if m == "monthly"}
    return {
        "site_id": site_id,
        "tier": ({
            "key": tier_row["key"], "label": (cfg["tiers"].get(tier_row["key"]) or {}).get("label", tier_row["key"]),
            "status": tier_row["effective_status"], "source": tier_row.get("source"),
            "paid_until": tier_row.get("paid_until"), "billing_mode": tier_row.get("billing_mode"),
            "id": tier_row.get("id"), "picks": (tier_row.get("config") or {}).get("picks") or [],
        } if tier_row else None),
        "addons": [{"id": r.get("id"), "key": r["key"], "status": r["effective_status"], "source": r.get("source"),
                    "paid_until": r.get("paid_until")} for r in c["rows"] if r["kind"] == "addon"],
        "features": sorted(c["features"]),
        "caps": c["caps"],
        "usage": monthly,
    }


def has_feature(db: Any, org_id: str, site_id: str, key: str, now: Optional[datetime] = None) -> bool:
    """True only if a live (active or grace) tier or add-on of this site includes the feature. Never raises;
    fails closed (False) on any error."""
    try:
        if not reg.is_feature(key) or not org_id or not site_id:
            return False
        return key in _compute(db, org_id, site_id, now or _now())["features"]
    except Exception as exc:  # S14 - fail closed
        logger.warning("site_entitlement.has_feature failed org=%s site=%s key=%s: %s", org_id, site_id, key, exc)
        return False


def consume(db: Any, org_id: str, site_id: str, feature_key: str, n: int = 1,
            now: Optional[datetime] = None) -> bool:
    """Use `n` units of the monthly cap behind a feature (AI messages, bulk recipients).
    True = allowed and counted. False = feature off, cap missing or 0, or cap reached -> the caller hands over to the
    owner instead of continuing. A cap that is not set means NO allowance (so cost can never run unchecked).
    The count moves with a conditional update (used must still equal what we read), so two requests at once can never
    both squeeze under the cap. Never raises; fails closed."""
    try:
        now = now or _now()
        cap_key = reg.cap_for_feature(feature_key)
        c = _compute(db, org_id, site_id, now)
        if feature_key not in c["features"]:
            return False
        if cap_key is None or reg.CAPS.get(cap_key) != "monthly":
            return True          # an uncapped feature: allowed whenever it is on
        if not isinstance(n, int) or n < 0:
            return False
        cap = c["caps"].get(cap_key, 0)
        if cap <= 0:
            return False
        if n == 0:
            return True
        ps = period_start(now).isoformat()
        for _ in range(3):
            row = _one((db.table("site_usage_counters").select("*").eq("org_id", org_id).eq("site_id", site_id)
                        .eq("cap_key", cap_key).eq("period_start", ps).limit(1).execute()).data)
            if row is None:
                try:
                    db.table("site_usage_counters").insert({
                        "org_id": org_id, "site_id": site_id, "cap_key": cap_key, "period_start": ps,
                        "used": 0, "updated_at": _iso(now)}).execute()
                except Exception:      # a parallel request created it first; read it again
                    pass
                continue
            used = int(row.get("used") or 0)
            if used + n > cap:
                return False
            res = (db.table("site_usage_counters").update({"used": used + n, "updated_at": _iso(now)})
                   .eq("id", row["id"]).eq("used", used).execute())
            if res.data:
                return True
        return False
    except Exception as exc:  # S14 - fail closed
        logger.warning("site_entitlement.consume failed org=%s site=%s key=%s: %s", org_id, site_id, feature_key, exc)
        return False


# ---------------------------------------------------------------------------
# Staff actions (grant / pause / resume / cancel)
# ---------------------------------------------------------------------------

def _log_event(db: Any, org_id: str, site_id: str, actor: str, event: str, detail: dict) -> None:
    try:
        db.table("site_events").insert({
            "org_id": org_id, "site_id": site_id, "order_id": None, "actor": actor, "event": event,
            "detail": detail, "created_at": _iso()}).execute()
    except Exception as exc:  # S14
        logger.warning("site_entitlement: event log failed site=%s event=%s: %s", site_id, event, exc)


def _site_exists(db: Any, org_id: str, site_id: str) -> None:
    row = _one((db.table("sites").select("id").eq("id", site_id).eq("org_id", org_id).is_("deleted_at", "null")
                .limit(1).execute()).data)
    if not row:
        raise EntitlementNotFound("Site not found")


def _clean_picks(tier: dict, picks) -> list:
    picks = [p for p in (picks or []) if isinstance(p, str)]
    out: list = []
    for p in picks:
        group = next((g for g in tier["pick_one"] if p in g), None)
        if group is None:
            raise EntitlementError("That choice isn't available for this tier.")
        if any(o in group for o in out):
            raise EntitlementError("Choose only one from each pair.")
        out.append(p)
    return out


def grant(db: Any, org_id: str, site_id: str, actor: str, kind: str, key: str, *,
          until: Optional[datetime] = None, picks: Optional[list] = None, billing_mode: str = "link",
          payer: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    """Staff switch a tier or add-on on for a site with no payment (source 'staff'). `until` None = no end date.
    A site has one tier: granting a different tier replaces the current one. Returns the entitlements."""
    now = now or _now()
    if kind not in ("tier", "addon"):
        raise EntitlementError("Choose a tier or an add-on.")
    if billing_mode not in ("link", "auto"):
        raise EntitlementError("Billing mode must be link or auto.")
    cfg = get_config(_settings(db, org_id))
    defs = cfg["tiers"] if kind == "tier" else cfg["addons"]
    if key not in defs:
        raise EntitlementError("Unknown tier." if kind == "tier" else "Unknown add-on.")
    if until is not None:
        until = _parse(until)
        if until is None or until <= now:
            raise EntitlementError("The end date must be in the future.")
    _site_exists(db, org_id, site_id)

    config: dict = {}
    if kind == "tier":
        config["picks"] = _clean_picks(defs[key], picks)
    payer = payer or {}
    fields = {
        "status": "active", "source": "staff", "billing_mode": billing_mode,
        "paid_until": _iso(until) if until else None, "grace_until": None, "next_reminder_at": None,
        "config": config, "updated_at": _iso(now),
        "payer_name": payer.get("name"), "payer_phone": payer.get("phone"), "payer_email": payer.get("email"),
    }
    q = db.table("site_addons").select("*").eq("org_id", org_id).eq("site_id", site_id).eq("kind", kind).neq("status", "cancelled")
    if kind == "addon":
        q = q.eq("key", key)
    existing = _one(q.limit(1).execute().data)
    if existing:
        db.table("site_addons").update({**fields, "key": key}).eq("id", existing["id"]).eq("org_id", org_id).execute()
        event = "site_addon_changed"
    else:
        db.table("site_addons").insert({
            "org_id": org_id, "site_id": site_id, "kind": kind, "key": key, "price_ngn": 0,
            "created_by": None, "created_at": _iso(now), **fields}).execute()
        event = "site_addon_granted"
    _log_event(db, org_id, site_id, actor, event,
               {"kind": kind, "key": key, "until": fields["paid_until"], "picks": config.get("picks")})
    return get_entitlements(db, org_id, site_id, now)


def set_status(db: Any, org_id: str, site_id: str, addon_id: str, action: str, actor: str, *,
               until: Optional[datetime] = None, now: Optional[datetime] = None) -> dict:
    """pause (active/grace -> paused), resume (paused -> active, optionally with a new end date), cancel (any -> cancelled).
    Conditional updates, so a double click or a parallel worker run changes nothing twice."""
    now = now or _now()
    if action not in ("pause", "resume", "cancel"):
        raise EntitlementError("Unknown action.")
    row = _one((db.table("site_addons").select("*").eq("id", addon_id).eq("org_id", org_id).eq("site_id", site_id)
                .limit(1).execute()).data)
    if not row:
        raise EntitlementNotFound("Add-on not found")
    if action == "pause":
        res = (db.table("site_addons").update({"status": "paused", "updated_at": _iso(now)})
               .eq("id", addon_id).eq("org_id", org_id).in_("status", ["active", "grace"]).execute())
    elif action == "resume":
        patch: dict = {"status": "active", "grace_until": None, "updated_at": _iso(now)}
        if until is not None:
            until = _parse(until)
            if until is None or until <= now:
                raise EntitlementError("The end date must be in the future.")
            patch["paid_until"] = _iso(until)
        res = (db.table("site_addons").update(patch).eq("id", addon_id).eq("org_id", org_id)
               .eq("status", "paused").execute())
    else:
        res = (db.table("site_addons").update({"status": "cancelled", "updated_at": _iso(now)})
               .eq("id", addon_id).eq("org_id", org_id).in_("status", ["pending", "active", "grace", "paused"]).execute())
    if not res.data:
        raise EntitlementError("That can't be done in its current state.")
    _log_event(db, org_id, site_id, actor, f"site_addon_{action}", {"addon_id": addon_id, "key": row.get("key")})
    return get_entitlements(db, org_id, site_id, now)


def overview(db: Any, org_id: str, now: Optional[datetime] = None) -> dict:
    """Staff overview numbers for the Sites page: how many live sites are on each plan, how many are waiting for
    payment or overdue, and the monthly value of what clients currently pay for. Raises on a database error (the
    overview route catches it so the rest of the page still loads)."""
    now = now or _now()
    cfg = get_config(_settings(db, org_id))
    live_sites = {s["id"] for s in (db.table("sites").select("id").eq("org_id", org_id).is_("deleted_at", "null")
                                    .execute()).data or []}
    rows = (db.table("site_addons").select("*").eq("org_id", org_id).neq("status", "cancelled").execute()).data or []
    tiers = {k: {"label": cfg["tiers"][k]["label"], "active": 0, "grace": 0, "pending": 0, "paused": 0} for k in cfg["tiers"]}
    addons_active = 0
    waiting = overdue = value = 0
    sites_on_plan: set = set()
    for r in rows:
        if r.get("site_id") not in live_sites:
            continue
        eff = effective_status(r, cfg, now)
        if r.get("kind") == "tier" and r.get("key") in tiers:
            tiers[r["key"]][eff] += 1
            if eff in ("active", "grace"):
                sites_on_plan.add(r["site_id"])
        elif r.get("kind") == "addon" and eff in ("active", "grace"):
            addons_active += 1
        waiting += 1 if eff == "pending" else 0
        overdue += 1 if eff == "grace" else 0
        if eff in ("active", "grace") and r.get("source") == "paid":
            d = (cfg["tiers"] if r.get("kind") == "tier" else cfg["addons"]).get(r.get("key")) or {}
            value += int(d.get("monthly_ngn") or 0)
    return {"tiers": tiers, "addons_active": addons_active, "sites_on_plan": len(sites_on_plan),
            "waiting_for_payment": waiting, "overdue": overdue, "monthly_value": value}
