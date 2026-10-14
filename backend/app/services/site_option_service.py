"""
app/services/site_option_service.py
-------------------------------------
SITE-OPTIONS OPT-1 - several design options for one client behind ONE link; the client picks one.

An option set groups up to 5 ordinary sites (any tier) made for the same client by the same builder. The set has a
private link (/o/{token}); the client opens it, looks at each design and taps "Choose this one". The builder is told,
then creates the payment link for the chosen site exactly as before (option A). Nothing about payment, publishing or
care plans changes: they only ever see the chosen site.

Rules (Trust, 14 Oct 2026):
  * max 5 sites per set (setting: pricing["options"]["max_items"]); max 10 open sets per builder (max_open_sets)
  * sites that are only options do NOT count in the builder's free-sites limit and cannot be checked out;
    the chosen site counts like any other (sites.option_offered turns false when it is picked)
  * the pick is not final: it can change until the chosen site has a paid order
  * unchosen options are kept 14 days after the latest pick (retention_days), then cancelled by the daily sweep
  * a set nobody picks from expires (expires_days, default 30): its sites go back to being ordinary sites

Safety: the pick is a compare-and-swap on the set row, so two taps / two devices cannot both win. Public lookups give
the same "not valid" answer for an unknown token. Org-scoped (S14); notifications never raise.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULTS = {"max_items": 5, "max_open_sets": 10, "retention_days": 14, "expires_days": 30}
OPEN_STATES = ("open", "chosen")
UNPAID_ORDER_STATUSES = ("pending_payment", "expired", "cancelled", "failed", "voided")
PICK_TEMPLATE_ENV = "SITE_OPTION_PICK_TEMPLATE"


class OptionError(Exception):
    status_code = 422
    code = "VALIDATION_ERROR"


class OptionNotFound(OptionError):
    status_code = 404
    code = "NOT_FOUND"


class OptionConflict(OptionError):
    status_code = 409
    code = "CONFLICT"


class OptionLimit(OptionError):
    status_code = 403
    code = "ACCESS_LIMIT"


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
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _int(value, default: int, low: int = 1, high: int = 100) -> int:
    try:
        return min(high, max(low, int(value)))
    except (TypeError, ValueError):
        return default


def get_config(settings: Optional[dict]) -> dict:
    raw = (((settings or {}).get("pricing") or {}).get("options")) or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "max_items": _int(raw.get("max_items"), DEFAULTS["max_items"], 2, 10),
        "max_open_sets": _int(raw.get("max_open_sets"), DEFAULTS["max_open_sets"], 1, 100),
        "retention_days": _int(raw.get("retention_days"), DEFAULTS["retention_days"], 1, 90),
        "expires_days": _int(raw.get("expires_days"), DEFAULTS["expires_days"], 1, 180),
    }


def _settings(db: Any, org_id: str) -> dict:
    return _one((db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data) or {}


def public_base() -> str:
    return os.environ.get("PUBLIC_API_URL", "https://opsra.onrender.com").rstrip("/")


def link_url(token: str) -> str:
    return f"{public_base()}/o/{token}"


def _log_event(db: Any, org_id: str, site_id: str, actor: str, event: str, detail: dict) -> None:
    try:
        db.table("site_events").insert({"org_id": org_id, "site_id": site_id, "order_id": None, "actor": actor,
                                        "event": event, "detail": detail, "created_at": _iso()}).execute()
    except Exception as exc:  # S14
        logger.warning("site_option: event log failed site=%s event=%s: %s", site_id, event, exc)


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def _get_set(db: Any, org_id: str, set_id: str, builder_id: Optional[str] = None) -> dict:
    q = db.table("site_option_sets").select("*").eq("id", set_id).eq("org_id", org_id)
    if builder_id:
        q = q.eq("builder_id", builder_id)
    row = _one(q.limit(1).execute().data)
    if not row:
        raise OptionNotFound("Option set not found")
    return row


def _items(db: Any, set_id: str) -> list:
    rows = (db.table("site_option_items").select("*").eq("set_id", set_id).execute()).data or []
    return sorted(rows, key=lambda r: (r.get("sort_order") or 0, str(r.get("created_at") or "")))


def site_paid(db: Any, org_id: str, site_id: str) -> bool:
    """True when the site has a paid first order (anything but pending/expired/cancelled). Errors count as NOT paid
    for display but the pick path treats a lookup failure as paid (fail closed: never swap a possibly paid site)."""
    rows = (db.table("site_orders").select("id, status").eq("org_id", org_id).eq("site_id", site_id)
            .eq("kind", "initial").execute()).data or []
    return any((r.get("status") or "") not in UNPAID_ORDER_STATUSES for r in rows)


def _site_paid_safe(db: Any, org_id: str, site_id: str) -> bool:
    try:
        return site_paid(db, org_id, site_id)
    except Exception as exc:  # S14 - fail closed
        logger.warning("site_option: paid lookup failed site=%s: %s", site_id, exc)
        return True


def _site_card(site: dict) -> dict:
    content = site.get("content") if isinstance(site.get("content"), dict) else {}
    hero = content.get("hero") if isinstance(content.get("hero"), dict) else {}
    return {
        "site_id": site.get("id"), "business_name": site.get("client_business_name"), "slug": site.get("slug"),
        "status": site.get("status"), "tier": site.get("tier") or "standard",
        "headline": (hero.get("headline") or "")[:140] or None,
        "preview_url": f"{public_base()}/s/{site.get('slug')}" if site.get("slug") else None,
    }


def get_set(db: Any, org_id: str, set_id: str, builder_id: Optional[str] = None) -> dict:
    """The full view for the builder / staff: link, status and every option with its site details."""
    s = _get_set(db, org_id, set_id, builder_id)
    items = _items(db, s["id"])
    sites = {}
    if items:
        rows = (db.table("sites").select("id, client_business_name, slug, status, tier, content")
                .eq("org_id", org_id).in_("id", [i["site_id"] for i in items]).execute()).data or []
        sites = {r["id"]: r for r in rows}
    out_items = []
    for i in items:
        card = _site_card(sites.get(i["site_id"]) or {"id": i["site_id"]})
        out_items.append({"id": i["id"], "label": i["label"], "status": i["status"], "sort_order": i.get("sort_order"), **card})
    return {
        "id": s["id"], "builder_id": s["builder_id"], "client_name": s.get("client_name"), "status": s["status"],
        "chosen_site_id": s.get("chosen_site_id"), "chosen_at": s.get("chosen_at"),
        "release_after": s.get("release_after"), "expires_at": s.get("expires_at"),
        "link": link_url(s["token"]), "items": out_items, "created_at": s.get("created_at"),
    }


def list_sets(db: Any, org_id: str, builder_id: Optional[str] = None, limit: int = 100) -> list:
    q = db.table("site_option_sets").select("*").eq("org_id", org_id)
    if builder_id:
        q = q.eq("builder_id", builder_id)
    rows = q.order("created_at", desc=True).limit(limit).execute().data or []
    out = []
    for s in rows:
        n = len((db.table("site_option_items").select("id").eq("set_id", s["id"]).execute()).data or [])
        out.append({"id": s["id"], "builder_id": s["builder_id"], "client_name": s.get("client_name"),
                    "status": s["status"], "options": n, "chosen_site_id": s.get("chosen_site_id"),
                    "expires_at": s.get("expires_at"), "link": link_url(s["token"]), "created_at": s.get("created_at")})
    return out


# ---------------------------------------------------------------------------
# create / attach / detach
# ---------------------------------------------------------------------------

def create_set(db: Any, org_id: str, builder_id: str, client_name: Optional[str], actor: str,
               site_ids: Optional[list] = None) -> dict:
    builder = _one((db.table("site_builders").select("id").eq("id", builder_id).eq("org_id", org_id).limit(1).execute()).data)
    if not builder:
        raise OptionNotFound("Builder not found")
    cfg = get_config(_settings(db, org_id))
    open_sets = (db.table("site_option_sets").select("id").eq("org_id", org_id).eq("builder_id", builder_id)
                 .in_("status", list(OPEN_STATES)).execute()).data or []
    if len(open_sets) >= cfg["max_open_sets"]:
        raise OptionLimit(f"You already have {cfg['max_open_sets']} open option sets. Finish or close one first.")
    name = (client_name or "").strip()[:120] or None
    now = _now()
    row = {"org_id": org_id, "builder_id": builder_id, "client_name": name, "token": secrets.token_urlsafe(24),
           "status": "open", "expires_at": _iso(now + timedelta(days=cfg["expires_days"])), "created_by": actor,
           "created_at": _iso(now), "updated_at": _iso(now)}
    created = _one(db.table("site_option_sets").insert(row).execute().data) or row
    for sid in (site_ids or [])[: cfg["max_items"]]:
        attach_site(db, org_id, created["id"], sid, None, actor)
    return get_set(db, org_id, created["id"])


def _attach_check(db: Any, org_id: str, s: dict, site_id: str, cfg: dict) -> dict:
    if s["status"] not in OPEN_STATES:
        raise OptionConflict("This option set is closed")
    site = _one((db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).is_("deleted_at", "null")
                 .limit(1).execute()).data)
    if not site:
        raise OptionNotFound("Site not found")
    if str(site.get("builder_id")) != str(s["builder_id"]):
        raise OptionError("That site belongs to a different builder")
    if site.get("status") in ("cancelled", "live"):
        raise OptionError("A live or cancelled site cannot be offered as an option")
    if site.get("option_set_id"):
        raise OptionConflict("That site is already part of an option set")
    if _site_paid_safe(db, org_id, site_id):
        raise OptionError("That site already has a payment, so it cannot be offered as an option")
    return site


def attach_site(db: Any, org_id: str, set_id: str, site_id: str, label: Optional[str], actor: str,
                builder_id: Optional[str] = None) -> dict:
    s = _get_set(db, org_id, set_id, builder_id)
    cfg = get_config(_settings(db, org_id))
    items = _items(db, s["id"])
    if len(items) >= cfg["max_items"]:
        raise OptionLimit(f"A set holds at most {cfg['max_items']} options")
    site = _attach_check(db, org_id, s, site_id, cfg)
    n = len(items)
    label = (label or "").strip()[:60] or f"Design {chr(65 + n) if n < 26 else n + 1}"
    now = _now()
    db.table("site_option_items").insert({"org_id": org_id, "set_id": s["id"], "site_id": site_id, "label": label,
                                          "sort_order": n, "status": "offered", "created_at": _iso(now)}).execute()
    updates = {"option_set_id": s["id"], "option_offered": True, "updated_at": _iso(now)}
    # The link must keep working while the client decides: previews of offered sites last at least as long as the set.
    keep_until = _parse(s.get("expires_at"))
    current = _parse(site.get("preview_expires_at"))
    if keep_until and (not current or current < keep_until):
        updates["preview_expires_at"] = _iso(keep_until)
    db.table("sites").update(updates).eq("id", site_id).eq("org_id", org_id).execute()
    _log_event(db, org_id, site_id, actor, "option_attached", {"set_id": s["id"], "label": label})
    return get_set(db, org_id, s["id"])


def detach_site(db: Any, org_id: str, set_id: str, site_id: str, actor: str, builder_id: Optional[str] = None) -> dict:
    s = _get_set(db, org_id, set_id, builder_id)
    item = _one((db.table("site_option_items").select("*").eq("set_id", s["id"]).eq("site_id", site_id).limit(1).execute()).data)
    if not item:
        raise OptionNotFound("That site is not in this set")
    if item["status"] == "chosen" or str(s.get("chosen_site_id")) == str(site_id):
        raise OptionConflict("The client has picked this design. Switch the pick to another design first.")
    # Taking a site out turns it back into an ordinary site, so the free-sites limit applies again (no way round it).
    from app.services import site_access_service as access
    builder = _one((db.table("site_builders").select("*").eq("id", s["builder_id"]).eq("org_id", org_id).limit(1).execute()).data)
    if builder:
        try:
            access.check_can_create(db, org_id, builder)
        except access.AccessBlocked as exc:
            raise OptionLimit(str(exc))
    db.table("site_option_items").delete().eq("id", item["id"]).execute()
    db.table("sites").update({"option_set_id": None, "option_offered": False, "updated_at": _iso()}) \
        .eq("id", site_id).eq("org_id", org_id).execute()
    _log_event(db, org_id, site_id, actor, "option_detached", {"set_id": s["id"]})
    return get_set(db, org_id, s["id"])


def close_set(db: Any, org_id: str, set_id: str, actor: str, builder_id: Optional[str] = None) -> dict:
    """Manual close: nothing more can be picked. Offered sites go back to being ordinary sites (they count again)."""
    s = _get_set(db, org_id, set_id, builder_id)
    if s["status"] not in OPEN_STATES:
        raise OptionConflict("This option set is already closed")
    if s.get("chosen_site_id"):
        raise OptionConflict("A design was picked. It closes by itself when the picked site is paid.")
    _release_sites(db, org_id, s, actor)
    db.table("site_option_sets").update({"status": "closed", "updated_at": _iso()}).eq("id", s["id"]).execute()
    return get_set(db, org_id, s["id"])


def _release_sites(db: Any, org_id: str, s: dict, actor: str) -> None:
    for i in _items(db, s["id"]):
        try:
            db.table("sites").update({"option_set_id": None, "option_offered": False, "updated_at": _iso()}) \
                .eq("id", i["site_id"]).eq("org_id", org_id).execute()
            db.table("site_option_items").update({"status": "released"}).eq("id", i["id"]).execute()
        except Exception as exc:  # S14
            logger.warning("site_option: release failed site=%s: %s", i.get("site_id"), exc)


# ---------------------------------------------------------------------------
# the client's side
# ---------------------------------------------------------------------------

def _by_token(db: Any, token: str) -> Optional[dict]:
    if not token or len(token) > 120:
        return None
    return _one((db.table("site_option_sets").select("*").eq("token", token).limit(1).execute()).data)


def public_view(db: Any, token: str) -> Optional[dict]:
    s = _by_token(db, token)
    if not s:
        return None
    org_id = s["org_id"]
    full = get_set(db, org_id, s["id"])
    builder = _one((db.table("site_builders").select("business_name, full_name").eq("id", s["builder_id"])
                    .eq("org_id", org_id).limit(1).execute()).data) or {}
    expired = s["status"] == "expired" or (s["status"] == "open" and (_parse(s.get("expires_at")) or _now()) < _now())
    paid = bool(s.get("chosen_site_id")) and _site_paid_safe(db, org_id, s["chosen_site_id"])
    can_choose = s["status"] in OPEN_STATES and not expired and not paid
    items = [i for i in full["items"] if i["status"] != "released" or s["status"] in OPEN_STATES]
    return {
        "status": s["status"], "expired": expired, "paid": paid, "can_choose": can_choose,
        "builder_name": builder.get("business_name") or builder.get("full_name"),
        "client_name": s.get("client_name"), "chosen_site_id": s.get("chosen_site_id"),
        "items": [{"id": i["id"], "label": i["label"], "business_name": i["business_name"], "headline": i["headline"],
                   "preview_url": i["preview_url"], "chosen": i["site_id"] == s.get("chosen_site_id"),
                   "site_status": i["status"]} for i in items],
    }


def choose_by_token(db: Any, token: str, item_id: str, now: Optional[datetime] = None) -> dict:
    s = _by_token(db, token)
    if not s:
        raise OptionNotFound("Link not valid")
    return _choose(db, s, item_id, "client", now or _now(), notify=True)


def choose_for_client(db: Any, org_id: str, set_id: str, item_id: str, actor: str,
                      builder_id: Optional[str] = None) -> dict:
    """The builder or staff picks on the client's behalf (the client told them in chat)."""
    s = _get_set(db, org_id, set_id, builder_id)
    return _choose(db, s, item_id, actor, _now(), notify=False)


def _choose(db: Any, s: dict, item_id: str, actor: str, now: datetime, notify: bool) -> dict:
    org_id = s["org_id"]
    if s["status"] not in OPEN_STATES:
        raise OptionConflict("This choice is closed")
    expires = _parse(s.get("expires_at"))
    if s["status"] == "open" and expires and expires < now:
        raise OptionConflict("This link has expired")
    item = _one((db.table("site_option_items").select("*").eq("id", item_id).eq("set_id", s["id"]).limit(1).execute()).data)
    if not item or item["status"] == "released":
        raise OptionNotFound("That design is not available")
    prev = s.get("chosen_site_id")
    if prev and str(prev) == str(item["site_id"]):
        return {"label": item["label"], "changed": False, "already": True}
    if prev and _site_paid_safe(db, org_id, prev):
        raise OptionConflict("A design has already been paid for, so the choice can't be changed")
    site = _one((db.table("sites").select("*").eq("id", item["site_id"]).eq("org_id", org_id).is_("deleted_at", "null")
                 .limit(1).execute()).data)
    if not site or site.get("status") == "cancelled":
        raise OptionConflict("That design is no longer available")
    cfg = get_config(_settings(db, org_id))
    release_after = now + timedelta(days=cfg["retention_days"])
    cas = db.table("site_option_sets").update({
        "status": "chosen", "chosen_site_id": item["site_id"], "chosen_at": _iso(now),
        "release_after": _iso(release_after), "updated_at": _iso(now)}) \
        .eq("id", s["id"]).in_("status", list(OPEN_STATES))
    cas = cas.eq("chosen_site_id", prev) if prev else cas.is_("chosen_site_id", "null")
    if not (cas.execute()).data:
        raise OptionConflict("The choice was just changed. Please reload the page and try again.")
    db.table("site_option_items").update({"status": "chosen"}).eq("id", item["id"]).execute()
    updates = {"option_offered": False, "updated_at": _iso(now)}
    keep = now + timedelta(days=30)
    cur = _parse(site.get("preview_expires_at"))
    if site.get("status") != "live" and (not cur or cur < keep):
        updates["preview_expires_at"] = _iso(keep)
    db.table("sites").update(updates).eq("id", item["site_id"]).eq("org_id", org_id).execute()
    if prev:
        try:
            db.table("site_option_items").update({"status": "offered"}).eq("set_id", s["id"]).eq("site_id", prev).execute()
            db.table("sites").update({"option_offered": True, "updated_at": _iso(now)}).eq("id", prev).eq("org_id", org_id).execute()
            # The old pick's unpaid payment link is switched off so it cannot be paid by mistake.
            db.table("site_orders").update({"status": "expired", "updated_at": _iso(now)}) \
                .eq("org_id", org_id).eq("site_id", prev).eq("kind", "initial").eq("status", "pending_payment").execute()
        except Exception as exc:  # S14 - the pick itself already succeeded
            logger.warning("site_option: switching away from site=%s left loose ends: %s", prev, exc)
    _log_event(db, org_id, item["site_id"], actor, "option_chosen",
               {"set_id": s["id"], "label": item["label"], "previous_site_id": prev})
    if notify:
        notify_builder(db, org_id, s, item, site)
    return {"label": item["label"], "changed": bool(prev), "already": False, "business_name": site.get("client_business_name")}


def notify_builder(db: Any, org_id: str, s: dict, item: dict, site: dict) -> None:
    """Tell the builder which design the client picked, with a button to create the payment link. Never raises."""
    try:
        builder = _one((db.table("site_builders").select("*").eq("id", s["builder_id"]).eq("org_id", org_id).limit(1).execute()).data)
        if not builder:
            return
        client = s.get("client_name") or site.get("client_business_name") or "Your client"
        business = site.get("client_business_name") or "the site"
        url = os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/") + "/builders"
        text = (f"{client} picked \"{item['label']}\" ({business}).\n"
                "Next step: create the payment link for this site in your builder portal and send it to your client.")
        from app.services import site_capture_service as cap
        if builder.get("phone_number"):
            cap._send_whatsapp(db, org_id, builder["phone_number"], text, cta=("Create payment link", url),
                               template_env=PICK_TEMPLATE_ENV,
                               template_params=[builder.get("full_name") or builder.get("business_name") or "there",
                                                client, item["label"], url])
        if builder.get("email"):
            cap._send_email(builder["email"], f"{client} picked a design", f"{text}\n\nOpen your builder portal: {url}")
    except Exception as exc:  # S14
        logger.warning("site_option: builder notice failed set=%s: %s", s.get("id"), exc)


# ---------------------------------------------------------------------------
# forms: a brief-form link made for a set builds an option site without using up a free-site slot
# ---------------------------------------------------------------------------

def eligible_sites(db: Any, org_id: str, builder_id: str, limit: int = 60) -> list:
    """The builder's sites that could be added to an option set: not live/cancelled, not in a set already, no payment.
    Newest first. Same rules as _attach_check so the picker never offers a site the add would refuse."""
    rows = (db.table("sites").select("id, client_business_name, slug, status, tier, option_set_id, created_at")
            .eq("org_id", org_id).eq("builder_id", builder_id).is_("deleted_at", "null").execute()).data or []
    rows = [r for r in rows if r.get("status") not in ("cancelled", "live") and not r.get("option_set_id")]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    out = []
    for r in rows[:limit]:
        if _site_paid_safe(db, org_id, r["id"]):
            continue
        out.append({"site_id": r["id"], "business_name": r.get("client_business_name"), "slug": r.get("slug"),
                    "status": r.get("status"), "tier": r.get("tier") or "standard",
                    "preview_url": f"{public_base()}/s/{r['slug']}" if r.get("slug") else None})
    return out


def usable_for_new_site(db: Any, org_id: str, set_id: Optional[str], builder_id: str) -> Optional[dict]:
    """The set (as a row) when a NEW site may be added to it right now (open/chosen, same builder, room left)."""
    if not set_id:
        return None
    try:
        s = _one((db.table("site_option_sets").select("*").eq("id", set_id).eq("org_id", org_id)
                  .eq("builder_id", builder_id).limit(1).execute()).data)
        if not s or s["status"] not in OPEN_STATES:
            return None
        cfg = get_config(_settings(db, org_id))
        if len(_items(db, s["id"])) >= cfg["max_items"]:
            return None
        return s
    except Exception as exc:  # S14 - fall back to the normal free-sites rule
        logger.warning("site_option: usable check failed set=%s: %s", set_id, exc)
        return None


def validate_set_for_builder(db: Any, org_id: str, set_id: str, builder_id: str) -> dict:
    s = usable_for_new_site(db, org_id, set_id, builder_id)
    if not s:
        raise OptionError("That option set is full, closed or not yours")
    return s


# ---------------------------------------------------------------------------
# the sweep (worker)
# ---------------------------------------------------------------------------

def run_sweep(db: Any, now: Optional[datetime] = None) -> dict:
    now = now or _now()
    out = {"expired": 0, "closed": 0, "cleaned": 0, "failed": 0}
    try:
        open_rows = (db.table("site_option_sets").select("*").eq("status", "open")
                     .lt("expires_at", _iso(now)).execute()).data or []
        for s in open_rows:
            try:
                _release_sites(db, s["org_id"], s, "system")
                db.table("site_option_sets").update({"status": "expired", "updated_at": _iso(now)}) \
                    .eq("id", s["id"]).eq("status", "open").execute()
                out["expired"] += 1
            except Exception as exc:  # S14
                out["failed"] += 1
                logger.warning("site_option sweep: expire failed set=%s: %s", s.get("id"), exc)
        chosen_rows = (db.table("site_option_sets").select("*").eq("status", "chosen").execute()).data or []
        cfg_cache: dict = {}
        for s in chosen_rows:
            try:
                org_id = s["org_id"]
                paid = _site_paid_safe(db, org_id, s["chosen_site_id"]) if s.get("chosen_site_id") else False
                due = (_parse(s.get("release_after")) or now) < now
                if not (paid or due):
                    continue
                updates = {"status": "closed", "updated_at": _iso(now)}
                if paid:        # paid: the other options stay available for the retention period, counted from payment
                    cfg = cfg_cache.setdefault(org_id, get_config(_settings(db, org_id)))
                    updates["release_after"] = _iso(now + timedelta(days=cfg["retention_days"]))
                claim = db.table("site_option_sets").update(updates).eq("id", s["id"]).eq("status", "chosen").execute()
                if not claim.data:
                    continue
                db.table("site_option_items").update({"status": "released"}) \
                    .eq("set_id", s["id"]).neq("site_id", s["chosen_site_id"]).execute()
                out["closed"] += 1
            except Exception as exc:  # S14
                out["failed"] += 1
                logger.warning("site_option sweep: close failed set=%s: %s", s.get("id"), exc)
        closed_rows = (db.table("site_option_sets").select("*").eq("status", "closed")
                       .lt("release_after", _iso(now)).execute()).data or []
        for s in closed_rows:
            try:
                for i in (db.table("site_option_items").select("*").eq("set_id", s["id"]).eq("status", "released").execute()).data or []:
                    if str(i["site_id"]) == str(s.get("chosen_site_id")):
                        continue
                    if _site_paid_safe(db, s["org_id"], i["site_id"]):
                        continue
                    res = (db.table("sites").update({"status": "cancelled", "rendered_html": None, "updated_at": _iso(now)})
                           .eq("id", i["site_id"]).eq("org_id", s["org_id"]).neq("status", "cancelled").neq("status", "live").execute())
                    if res.data:
                        _log_event(db, s["org_id"], i["site_id"], "system", "option_cleaned_up", {"set_id": s["id"]})
                        out["cleaned"] += 1
            except Exception as exc:  # S14
                out["failed"] += 1
                logger.warning("site_option sweep: cleanup failed set=%s: %s", s.get("id"), exc)
    except Exception as exc:  # S14
        out["failed"] += 1
        logger.warning("site_option sweep failed: %s", exc)
    return out
