"""
app/services/site_version_share_service.py
--------------------------------------------
SITE-OPTIONS OPT-3 - share several VERSIONS of one client's Premium site behind ONE private link (/v/{token}).
The client opens each version, then picks one. The pick becomes the site's current design (its preview) straight away,
the builder is told, and the client can change it until the site is paid. Free: it costs no site slot and no payment.

Tables: site_version_shares (one site + link + pick), site_version_items (the versions included, max 5).
Errors reuse site_option_service's OptionError family so the routers handle both features the same way.
S14: nothing here raises out of best-effort code (notice, sweep, event log). Pattern 28: org_id always comes from the caller.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from app.services import site_option_service as opt
from app.services.site_option_service import (OPEN_STATES, OptionConflict, OptionError, OptionLimit, OptionNotFound,
                                              _int, _iso, _log_event, _now, _one, _parse, _settings, get_config, public_base)

logger = logging.getLogger(__name__)
NO_VERSIONS = "That site has no saved versions to share yet."


def link_url(token: str) -> str:
    return f"{public_base()}/v/{token}"


def _item_url(token: str, item_id: str) -> str:
    return f"{public_base()}/v/{token}/view/{item_id}"


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def _site(db: Any, org_id: str, site_id: str, builder_id: Optional[str] = None) -> dict:
    site = _one((db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).is_("deleted_at", "null")
                 .limit(1).execute()).data)
    if not site or (builder_id and str(site.get("builder_id")) != str(builder_id)):
        raise OptionNotFound("Site not found")
    return site


def _share(db: Any, org_id: str, share_id: str, builder_id: Optional[str] = None) -> dict:
    q = db.table("site_version_shares").select("*").eq("id", share_id).eq("org_id", org_id)
    if builder_id:
        q = q.eq("builder_id", builder_id)
    row = _one(q.limit(1).execute().data)
    if not row:
        raise OptionNotFound("Version link not found")
    return row


def _items(db: Any, share_id: str) -> list:
    rows = (db.table("site_version_items").select("*").eq("share_id", share_id).execute()).data or []
    return sorted(rows, key=lambda r: (r.get("sort_order") or 0, str(r.get("created_at") or "")))


SHAREABLE_TIERS = ("premium", "imported")     # the two kinds of site that keep several saved designs


def _history(db: Any, org_id: str, site: dict) -> list:
    """Saved versions of a Premium (written designs) or Imported (uploaded sites) site, newest first, never held-back ones."""
    if (site.get("tier") or "standard") == "imported":
        from app.services import site_import_render
        out = []
        for d in site_import_render.designs(db, org_id, site):
            if d.get("staged") or d.get("status") != "ready":
                continue
            out.append({"id": d["id"], "version": d.get("version"), "kind": "import",
                        "label": d.get("filename") or "Uploaded site", "created_at": d.get("created_at"),
                        "is_current": bool(d.get("active")), "can_restore": not d.get("active")})
        return out
    from app.services import site_premium_history
    return site_premium_history.history(db, org_id, site)


def site_versions(db: Any, org_id: str, site_id: str, builder_id: Optional[str] = None) -> list:
    """The saved versions of a Premium or Imported site that can be shared (newest first)."""
    site = _site(db, org_id, site_id, builder_id)
    if (site.get("tier") or "standard") not in SHAREABLE_TIERS:
        return []
    try:
        return _history(db, org_id, site)
    except Exception as exc:  # S14
        logger.warning("site_version: history failed site=%s: %s", site_id, exc)
        return []


def premium_sites(db: Any, org_id: str, builder_id: Optional[str] = None, limit: int = 60) -> list:
    """Premium sites that could be shared, newest first: one builder's, or every builder's when builder_id is None (staff).
    Each row says which site it is (business name, preview link, status, builder) and how many saved versions it has;
    a site needs at least two versions to be worth sharing, the screen disables the ones with fewer."""
    q = db.table("sites").select("id, builder_id, client_business_name, slug, status, tier, created_at") \
        .eq("org_id", org_id).is_("deleted_at", "null")
    if builder_id:
        q = q.eq("builder_id", builder_id)
    rows = q.execute().data or []
    rows = [r for r in rows if (r.get("tier") or "standard") in SHAREABLE_TIERS and r.get("status") != "cancelled"]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    rows = rows[:limit]
    names = {}
    bids = list({r["builder_id"] for r in rows if r.get("builder_id")})
    if bids:
        for b in (db.table("site_builders").select("id, business_name, full_name").eq("org_id", org_id).in_("id", bids).execute()).data or []:
            names[b["id"]] = b.get("business_name") or b.get("full_name")
    out = []
    for r in rows:
        out.append({"site_id": r["id"], "business_name": r.get("client_business_name"), "status": r.get("status"),
                    "builder_id": r.get("builder_id"), "builder_name": names.get(r.get("builder_id")),
                    "preview_url": f"{public_base()}/s/{r['slug']}" if r.get("slug") else None,
                    "versions": len(site_versions(db, org_id, r["id"])), "created_at": r.get("created_at")})
    return out


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------

def _versions_by_id(db: Any, org_id: str, ids: list) -> dict:
    if not ids:
        return {}
    rows = (db.table("site_designs").select("id, version, kind, created_at").eq("org_id", org_id).in_("id", ids)
            .execute()).data or []
    return {r["id"]: r for r in rows}


def get_share(db: Any, org_id: str, share_id: str, builder_id: Optional[str] = None) -> dict:
    s = _share(db, org_id, share_id, builder_id)
    items = _items(db, s["id"])
    site = _one((db.table("sites").select("id, client_business_name, slug, status, current_design_id")
                 .eq("id", s["site_id"]).eq("org_id", org_id).limit(1).execute()).data) or {}
    designs = _versions_by_id(db, org_id, [i["design_id"] for i in items])
    out = []
    for i in items:
        d = designs.get(i["design_id"]) or {}
        out.append({"id": i["id"], "design_id": i["design_id"], "label": i["label"], "version": d.get("version"),
                    "created_at": d.get("created_at"), "chosen": str(i["design_id"]) == str(s.get("chosen_design_id")),
                    "is_current": str(i["design_id"]) == str(site.get("current_design_id")),
                    "preview_url": _item_url(s["token"], i["id"])})
    return {"id": s["id"], "site_id": s["site_id"], "builder_id": s["builder_id"], "business_name": site.get("client_business_name"),
            "client_name": s.get("client_name"), "status": s["status"], "chosen_design_id": s.get("chosen_design_id"),
            "chosen_at": s.get("chosen_at"), "expires_at": s.get("expires_at"), "link": link_url(s["token"]),
            "paid": bool(s.get("chosen_design_id")) and opt._site_paid_safe(db, org_id, s["site_id"]),
            "items": out, "created_at": s.get("created_at")}


def list_shares(db: Any, org_id: str, builder_id: Optional[str] = None, limit: int = 100) -> list:
    q = db.table("site_version_shares").select("*").eq("org_id", org_id)
    if builder_id:
        q = q.eq("builder_id", builder_id)
    rows = q.order("created_at", desc=True).limit(limit).execute().data or []
    names = {}
    ids = list({r["site_id"] for r in rows})
    if ids:
        for x in (db.table("sites").select("id, client_business_name").eq("org_id", org_id).in_("id", ids).execute()).data or []:
            names[x["id"]] = x.get("client_business_name")
    out = []
    for s in rows:
        n = len((db.table("site_version_items").select("id").eq("share_id", s["id"]).execute()).data or [])
        out.append({"id": s["id"], "site_id": s["site_id"], "builder_id": s["builder_id"], "business_name": names.get(s["site_id"]),
                    "client_name": s.get("client_name"), "status": s["status"], "versions": n,
                    "chosen_design_id": s.get("chosen_design_id"), "expires_at": s.get("expires_at"),
                    "link": link_url(s["token"]), "created_at": s.get("created_at")})
    return out


# ---------------------------------------------------------------------------
# create / add / remove / close
# ---------------------------------------------------------------------------

def _usable_designs(db: Any, org_id: str, site: dict) -> dict:
    return {h["id"]: h for h in _history(db, org_id, site)}


def preview_html(db: Any, org_id: str, site_id: str, design_id: str, builder_id: Optional[str] = None) -> str:
    """One saved version of a site as a full page (for the builder / staff Preview button). Raises OptionNotFound."""
    site = _site(db, org_id, site_id, builder_id)
    if (site.get("tier") or "standard") not in SHAREABLE_TIERS or design_id not in {h["id"] for h in _history(db, org_id, site)}:
        raise OptionNotFound("Version not found")
    assets = (db.table("site_assets").select("id, public_url").eq("site_id", site["id"]).execute()).data or []
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in assets}
    try:
        if (site.get("tier") or "standard") == "imported":
            from app.services import site_import_render
            return site_import_render.preview_design(db, org_id, site, design_id, assets_by_id)
        from app.services import site_premium_service
        return site_premium_service.preview_design(db, org_id, site, design_id, assets_by_id)
    except Exception as exc:
        logger.warning("site_version: preview failed site=%s design=%s: %s", site_id, design_id, exc)
        raise OptionNotFound("That version can't be shown right now")


def _label_for(version: Any, n: int, label: Optional[str]) -> str:
    return (label or "").strip()[:60] or (f"Version {version}" if version else f"Option {n + 1}")


def create_share(db: Any, org_id: str, site_id: str, client_name: Optional[str], design_ids: list, actor: str,
                 builder_id: Optional[str] = None) -> dict:
    site = _site(db, org_id, site_id, builder_id)
    if (site.get("tier") or "standard") not in SHAREABLE_TIERS:
        raise OptionError("Only Premium and uploaded sites keep saved versions to share.")
    if site.get("status") == "cancelled":
        raise OptionError("This site is cancelled.")
    if opt._site_paid_safe(db, org_id, site_id):
        raise OptionConflict("This site already has a payment, so there is nothing left to choose.")
    owner = site["builder_id"]
    cfg = get_config(_settings(db, org_id))
    mine = (db.table("site_version_shares").select("id, site_id").eq("org_id", org_id).eq("builder_id", owner)
            .in_("status", list(OPEN_STATES)).execute()).data or []
    if any(str(m["site_id"]) == str(site_id) for m in mine):
        raise OptionConflict("This site already has an open version link. Use it, or close it first.")
    if len(mine) >= cfg["max_open_sets"]:
        raise OptionLimit(f"You already have {cfg['max_open_sets']} open links. Finish or close one first.")
    usable = _usable_designs(db, org_id, site)
    chosen = []
    for d in design_ids or []:
        if d not in usable:
            raise OptionError("One of those versions is not available to share.")
        if d not in chosen:
            chosen.append(d)
    if len(chosen) < 1:
        raise OptionError("Pick at least one version to share.") if usable else OptionError(NO_VERSIONS)
    if len(chosen) > cfg["max_items"]:
        raise OptionLimit(f"A link holds at most {cfg['max_items']} versions")
    now = _now()
    expires = now + timedelta(days=cfg["expires_days"])
    row = {"org_id": org_id, "site_id": site_id, "builder_id": owner, "client_name": (client_name or "").strip()[:120] or None,
           "token": secrets.token_urlsafe(24), "status": "open", "expires_at": _iso(expires), "created_by": actor,
           "created_at": _iso(now), "updated_at": _iso(now)}
    created = _one(db.table("site_version_shares").insert(row).execute().data) or row
    for n, d in enumerate(chosen):
        db.table("site_version_items").insert({"org_id": org_id, "share_id": created["id"], "design_id": d,
                                               "label": _label_for(usable[d].get("version"), n, None), "sort_order": n,
                                               "created_at": _iso(now)}).execute()
    _keep_preview_alive(db, org_id, site, expires)
    _log_event(db, org_id, site_id, actor, "version_share_created", {"share_id": created["id"], "versions": len(chosen)})
    return get_share(db, org_id, created["id"])


def _keep_preview_alive(db: Any, org_id: str, site: dict, until: datetime) -> None:
    """The client's link must keep working while they decide: the site's preview lasts at least as long as the link."""
    try:
        cur = _parse(site.get("preview_expires_at"))
        if site.get("status") != "live" and (not cur or cur < until):
            db.table("sites").update({"preview_expires_at": _iso(until), "updated_at": _iso()}) \
                .eq("id", site["id"]).eq("org_id", org_id).execute()
    except Exception as exc:  # S14
        logger.warning("site_version: keep-alive failed site=%s: %s", site.get("id"), exc)


def add_version(db: Any, org_id: str, share_id: str, design_id: str, label: Optional[str], actor: str,
                builder_id: Optional[str] = None) -> dict:
    s = _share(db, org_id, share_id, builder_id)
    if s["status"] not in OPEN_STATES:
        raise OptionConflict("This link is closed")
    cfg = get_config(_settings(db, org_id))
    items = _items(db, s["id"])
    if len(items) >= cfg["max_items"]:
        raise OptionLimit(f"A link holds at most {cfg['max_items']} versions")
    if any(str(i["design_id"]) == str(design_id) for i in items):
        raise OptionConflict("That version is already in this link")
    site = _site(db, org_id, s["site_id"])
    usable = _usable_designs(db, org_id, site)
    if design_id not in usable:
        raise OptionError("That version is not available to share.")
    db.table("site_version_items").insert({"org_id": org_id, "share_id": s["id"], "design_id": design_id,
                                           "label": _label_for(usable[design_id].get("version"), len(items), label),
                                           "sort_order": len(items), "created_at": _iso()}).execute()
    _log_event(db, org_id, s["site_id"], actor, "version_share_added", {"share_id": s["id"], "design_id": design_id})
    return get_share(db, org_id, s["id"])


def remove_version(db: Any, org_id: str, share_id: str, item_id: str, actor: str, builder_id: Optional[str] = None) -> dict:
    s = _share(db, org_id, share_id, builder_id)
    if s["status"] not in OPEN_STATES:
        raise OptionConflict("This link is closed")
    items = _items(db, s["id"])
    item = next((i for i in items if str(i["id"]) == str(item_id)), None)
    if not item:
        raise OptionNotFound("That version is not in this link")
    if str(item["design_id"]) == str(s.get("chosen_design_id")):
        raise OptionConflict("The client picked this version. Switch the pick to another version first.")
    if len(items) <= 1:
        raise OptionConflict("A link needs at least one version. Close it instead.")
    db.table("site_version_items").delete().eq("id", item["id"]).execute()
    _log_event(db, org_id, s["site_id"], actor, "version_share_removed", {"share_id": s["id"], "design_id": item["design_id"]})
    return get_share(db, org_id, s["id"])


def close_share(db: Any, org_id: str, share_id: str, actor: str, builder_id: Optional[str] = None) -> dict:
    s = _share(db, org_id, share_id, builder_id)
    if s["status"] not in OPEN_STATES:
        raise OptionConflict("This link is already closed")
    db.table("site_version_shares").update({"status": "closed", "updated_at": _iso()}).eq("id", s["id"]).execute()
    _log_event(db, org_id, s["site_id"], actor, "version_share_closed", {"share_id": s["id"]})
    return get_share(db, org_id, s["id"])


# ---------------------------------------------------------------------------
# the client's side
# ---------------------------------------------------------------------------

def _by_token(db: Any, token: str) -> Optional[dict]:
    if not token or len(token) > 120:
        return None
    return _one((db.table("site_version_shares").select("*").eq("token", token).limit(1).execute()).data)


def _expired(s: dict, now: Optional[datetime] = None) -> bool:
    return s["status"] == "expired" or (s["status"] == "open" and (_parse(s.get("expires_at")) or (now or _now())) < (now or _now()))


def public_view(db: Any, token: str) -> Optional[dict]:
    s = _by_token(db, token)
    if not s:
        return None
    org_id = s["org_id"]
    full = get_share(db, org_id, s["id"])
    builder = _one((db.table("site_builders").select("business_name, full_name").eq("id", s["builder_id"])
                    .eq("org_id", org_id).limit(1).execute()).data) or {}
    expired = _expired(s)
    paid = bool(s.get("chosen_design_id")) and opt._site_paid_safe(db, org_id, s["site_id"])
    return {"status": s["status"], "expired": expired, "paid": paid,
            "can_choose": s["status"] in OPEN_STATES and not expired and not paid,
            "builder_name": builder.get("business_name") or builder.get("full_name"), "client_name": s.get("client_name"),
            "business_name": full.get("business_name"), "chosen_design_id": s.get("chosen_design_id"),
            "items": [{"id": i["id"], "label": i["label"], "version": i["version"], "chosen": i["chosen"]} for i in full["items"]]}


def render_version(db: Any, token: str, item_id: str) -> str:
    """The full page of one shared version, with the site's current content. Nothing changes. Raises OptionNotFound."""
    s = _by_token(db, token)
    if not s or s["status"] not in OPEN_STATES or _expired(s):
        raise OptionNotFound("Link not valid")
    item = _one((db.table("site_version_items").select("*").eq("id", item_id).eq("share_id", s["id"]).limit(1).execute()).data)
    if not item:
        raise OptionNotFound("Version not found")
    site = _site(db, s["org_id"], s["site_id"])
    from app.services import site_import_render, site_premium_service
    assets = (db.table("site_assets").select("id, public_url").eq("site_id", site["id"]).execute()).data or []
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in assets}
    try:
        if (site.get("tier") or "standard") == "imported":
            return site_import_render.preview_design(db, s["org_id"], site, item["design_id"], assets_by_id)
        return site_premium_service.preview_design(db, s["org_id"], site, item["design_id"], assets_by_id)
    except Exception as exc:
        logger.warning("site_version: render failed share=%s item=%s: %s", s["id"], item_id, exc)
        raise OptionNotFound("That version can't be shown right now")


def choose_by_token(db: Any, token: str, item_id: str, now: Optional[datetime] = None) -> dict:
    s = _by_token(db, token)
    if not s:
        raise OptionNotFound("Link not valid")
    return _choose(db, s, item_id, "client", now or _now(), notify=True)


def choose_for_client(db: Any, org_id: str, share_id: str, item_id: str, actor: str, builder_id: Optional[str] = None) -> dict:
    """The builder or staff records the pick on the client's behalf (the client told them in chat)."""
    return _choose(db, _share(db, org_id, share_id, builder_id), item_id, actor, _now(), notify=False)


def _choose(db: Any, s: dict, item_id: str, actor: str, now: datetime, notify: bool) -> dict:
    org_id = s["org_id"]
    if s["status"] not in OPEN_STATES:
        raise OptionConflict("This choice is closed")
    if _expired(s, now):
        raise OptionConflict("This link has expired")
    item = _one((db.table("site_version_items").select("*").eq("id", item_id).eq("share_id", s["id"]).limit(1).execute()).data)
    if not item:
        raise OptionNotFound("That version is not available")
    prev = s.get("chosen_design_id")
    if prev and str(prev) == str(item["design_id"]):
        return {"label": item["label"], "changed": False, "already": True}
    if opt._site_paid_safe(db, org_id, s["site_id"]):       # fail closed: never change a possibly paid site's design
        raise OptionConflict("This site has already been paid for, so the choice can't be changed")
    site = _site(db, org_id, s["site_id"])
    if site.get("status") == "cancelled":
        raise OptionConflict("This site is no longer available")
    cas = db.table("site_version_shares").update({"status": "chosen", "chosen_design_id": item["design_id"],
                                                  "chosen_at": _iso(now), "updated_at": _iso(now)}) \
        .eq("id", s["id"]).in_("status", list(OPEN_STATES))
    cas = cas.eq("chosen_design_id", prev) if prev else cas.is_("chosen_design_id", "null")
    if not (cas.execute()).data:
        raise OptionConflict("The choice was just changed. Please reload the page and try again.")
    try:
        if (site.get("tier") or "standard") == "imported":
            from app.services import site_import_render
            site_import_render.activate(db, org_id, site, item["design_id"], actor="client")
        else:
            from app.services import site_premium_service
            site_premium_service.use_design(db, org_id, site, item["design_id"])
    except Exception as exc:
        # Put the share back as it was: the site still shows its old design, so nothing may claim otherwise.
        try:
            db.table("site_version_shares").update({"status": s["status"], "chosen_design_id": prev,
                                                    "chosen_at": s.get("chosen_at"), "updated_at": _iso(now)}) \
                .eq("id", s["id"]).execute()
        except Exception as undo_exc:  # S14
            logger.warning("site_version: rollback failed share=%s: %s", s["id"], undo_exc)
        logger.warning("site_version: use_design failed share=%s: %s", s["id"], exc)
        raise OptionConflict("That version can't be applied right now. Nothing was changed.")
    _keep_preview_alive(db, org_id, site, now + timedelta(days=30))
    _log_event(db, org_id, s["site_id"], actor, "version_chosen",
               {"share_id": s["id"], "label": item["label"], "design_id": item["design_id"], "previous_design_id": prev})
    if notify:
        notify_builder(db, org_id, s, item, site)
    return {"label": item["label"], "changed": bool(prev), "already": False, "business_name": site.get("client_business_name")}


def notify_builder(db: Any, org_id: str, s: dict, item: dict, site: dict) -> None:
    """Tell the builder which version the client picked, with a button to create the payment link. Never raises."""
    try:
        builder = _one((db.table("site_builders").select("*").eq("id", s["builder_id"]).eq("org_id", org_id).limit(1).execute()).data)
        if not builder:
            return
        client = s.get("client_name") or site.get("client_business_name") or "Your client"
        business = site.get("client_business_name") or "the site"
        url = os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/") + "/builders"
        text = (f"{client} picked \"{item['label']}\" for {business}. It is now the site's preview.\n"
                "Next step: create the payment link in your builder portal and send it to your client.")
        from app.services import site_capture_service as cap
        if builder.get("phone_number"):
            cap._send_whatsapp(db, org_id, builder["phone_number"], text, cta=("Create payment link", url),
                               template_env=opt.PICK_TEMPLATE_ENV,
                               template_params=[builder.get("full_name") or builder.get("business_name") or "there",
                                                client, item["label"], url])
        if builder.get("email"):
            cap._send_email(builder["email"], f"{client} picked a version", f"{text}\n\nOpen your builder portal: {url}")
    except Exception as exc:  # S14
        logger.warning("site_version: builder notice failed share=%s: %s", s.get("id"), exc)


# ---------------------------------------------------------------------------
# hourly sweep
# ---------------------------------------------------------------------------

def run_sweep(db: Any, now: Optional[datetime] = None) -> dict:
    """Unpicked links past their date expire; a link whose picked site has been paid closes. Never raises."""
    now = now or _now()
    out = {"expired": 0, "closed": 0, "failed": 0}
    try:
        rows = (db.table("site_version_shares").select("*").in_("status", list(OPEN_STATES)).execute()).data or []
    except Exception as exc:  # S14
        logger.warning("site_version: sweep read failed: %s", exc)
        out["failed"] += 1
        return out
    for s in rows:
        try:
            if s["status"] == "open" and (_parse(s.get("expires_at")) or now) < now:
                db.table("site_version_shares").update({"status": "expired", "updated_at": _iso(now)}).eq("id", s["id"]).execute()
                out["expired"] += 1
            elif s["status"] == "chosen" and opt.site_paid(db, s["org_id"], s["site_id"]):
                db.table("site_version_shares").update({"status": "closed", "updated_at": _iso(now)}).eq("id", s["id"]).execute()
                out["closed"] += 1
        except Exception as exc:  # S14
            out["failed"] += 1
            logger.warning("site_version: sweep failed share=%s: %s", s.get("id"), exc)
    return out
