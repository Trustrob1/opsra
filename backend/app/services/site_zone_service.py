"""
app/services/site_zone_service.py
----------------------------------
SITE-ZONES — for domains WE buy for a client: put the domain's DNS on Cloudflare and connect it to the
`opsra-sites` Worker with no DNS record pasted by anyone.

Flow: connect_domain() creates the domain as a zone in our Cloudflare account and returns the two
nameservers Cloudflare assigns. Staff set those nameservers once at the registrar (QServers has no API,
so that one step stays manual). When Cloudflare reports the zone active, the domain and its `www.` form
are attached to the Worker as Worker custom domains; Cloudflare creates the DNS records and the SSL
certificates by itself. Calling connect_domain() again is the "check again": it is safe to repeat.

Rules:
- Settings: CLOUDFLARE_API_TOKEN (needs Zone:Edit, DNS:Edit on all zones and Workers Scripts:Edit on the
  account), CLOUDFLARE_ACCOUNT_ID, SITES_WORKER_NAME. Missing token/account = "not set up".
- Never creates a zone in a way that can overwrite DNS: attaching a Worker domain fails (plain message)
  if the zone already has a conflicting record, rather than replacing it.
- Moving a domain's nameservers replaces its DNS at the registrar. Fine for new domains; the popup warns
  that an existing domain's email records must be copied first.
- A hostname is reported live only when the zone is active, the Worker domain is attached AND the address
  answers over HTTPS (the certificate can take a minute or two after attaching).
- Errors are SiteOpsError subclasses (shared with site_cloudflare_service) so routers map them to 4xx/5xx.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.site_cloudflare_service import (
    CloudflareClient, HostnameError, HostnamesNotConfigured, hostnames_for, worker_name,
)
from app.services.site_publish_service import normalise_domain

logger = logging.getLogger(__name__)

MODE_ZONE = "cloudflare_zone"
MODE_CNAME = "client_cname"


def _settings():
    from app.config import get_settings
    return get_settings()


def make_client() -> tuple:
    """Returns (client, account_id). Raises HostnamesNotConfigured when the zone feature isn't set up."""
    s = _settings()
    token = getattr(s, "CLOUDFLARE_API_TOKEN", "")
    account = getattr(s, "CLOUDFLARE_ACCOUNT_ID", "")
    if not (token and account):
        raise HostnamesNotConfigured("Cloudflare DNS for new domains isn't set up yet. Add the Cloudflare account ID to the server first.")
    return CloudflareClient(token), account


def is_configured() -> bool:
    s = _settings()
    return bool(getattr(s, "CLOUDFLARE_API_TOKEN", "") and getattr(s, "CLOUDFLARE_ACCOUNT_ID", ""))


def _find_zone(client: Any, account: str, domain: str) -> Optional[dict]:
    body = client.request("GET", "/zones", params={"name": domain, "account.id": account})
    for row in body.get("result") or []:
        if str(row.get("name", "")).lower() == domain:
            return row
    return None


def _create_zone(client: Any, account: str, domain: str) -> dict:
    body = client.request("POST", "/zones", json={"account": {"id": account}, "name": domain, "type": "full"})
    return body.get("result") or {"name": domain, "status": "pending"}


def _attach(client: Any, account: str, zone_id: str, hostname: str, script: str) -> None:
    """Attaches the hostname to the Worker as a Worker custom domain (idempotent PUT)."""
    client.request("PUT", f"/accounts/{account}/workers/domains", json={
        "hostname": hostname, "service": script, "zone_id": zone_id, "environment": "production",
    })


def _attached(client: Any, account: str, hostname: str, script: str) -> bool:
    body = client.request("GET", f"/accounts/{account}/workers/domains", params={"hostname": hostname})
    return any(str(r.get("hostname", "")).lower() == hostname and r.get("service") == script
               for r in (body.get("result") or []))


def _answers_https(hostname: str) -> bool:
    """True when the address answers over HTTPS (any status below 500). Never raises."""
    try:
        import httpx
        return httpx.get(f"https://{hostname}/", timeout=6.0, follow_redirects=False).status_code < 500
    except Exception:
        return False


def _host_row(hostname: str, zone_status: str, attached: bool, live: bool) -> dict:
    if live:
        status, ssl = "active", "active"
    elif zone_status != "active":
        status, ssl = "waiting_nameservers", "none"
    elif attached:
        status, ssl = "pending", "initializing"
    else:
        status, ssl = "pending", "none"
    return {"hostname": hostname, "id": None, "status": status, "ssl_status": ssl, "active": live, "errors": []}


def _result(domain: str, zone: Optional[dict], rows: list) -> dict:
    zone_status = (zone or {}).get("status") or "none"
    return {
        "mode": MODE_ZONE, "domain": domain, "target": None, "dns": [],
        "zone_id": (zone or {}).get("id"), "zone_status": zone_status,
        "nameservers": list((zone or {}).get("name_servers") or []),
        "hostnames": rows, "route_ok": True,
        "all_active": bool(rows) and all(r["active"] for r in rows),
    }


def connect_domain(domain: str, create: bool = True, client: Any = None, account: Optional[str] = None,
                   script: Optional[str] = None, probe=_answers_https) -> dict:
    """Creates the domain's zone if needed (create=True), and once the zone is active attaches both
    addresses to the Worker. Returns {mode, domain, zone_id, zone_status, nameservers, hostnames,
    all_active, ...}. With create=False and no zone, returns zone_status 'none' without creating anything."""
    if client is None:
        client, account = make_client()
    d = normalise_domain(domain)
    script = script or worker_name()
    zone = _find_zone(client, account, d)
    if zone is None and create:
        zone = _create_zone(client, account, d)
    hosts = hostnames_for(d)
    if zone is None:
        return _result(d, None, [_host_row(h, "none", False, False) for h in hosts])

    zone_status = zone.get("status") or "pending"
    if zone_status != "active":
        # Nudge Cloudflare to re-check the nameservers now instead of waiting for its next scheduled check.
        try:
            client.request("PUT", f"/zones/{zone['id']}/activation_check")
        except HostnameError:
            pass
        fresh = client.request("GET", f"/zones/{zone['id']}").get("result") or {}
        zone = {**zone, **{k: fresh[k] for k in ("status", "name_servers") if k in fresh}}
        zone_status = zone.get("status") or "pending"

    rows = []
    for h in hosts:
        attached = False
        if zone_status == "active":
            if not _attached(client, account, h, script):
                _attach(client, account, zone["id"], h, script)
            attached = True
        rows.append(_host_row(h, zone_status, attached, attached and probe(h)))
    return _result(d, zone, rows)


def existing_zone(domain: str, client: Any = None, account: Optional[str] = None) -> Optional[dict]:
    """The domain's zone in our account, or None (also None when the zone feature isn't set up)."""
    try:
        if client is None:
            client, account = make_client()
    except HostnamesNotConfigured:
        return None
    return _find_zone(client, account, normalise_domain(domain))


# ---- which flow a domain uses, and remembering the zone state ---------------------------------------

def _domain_row(db, org_id: str, domain: str) -> Optional[dict]:
    d = normalise_domain(domain)
    try:
        rows = (db.table("site_domains").select("id, dns_mode").eq("org_id", org_id)
                .in_("domain", [d, f"www.{d}"]).limit(1).execute()).data or []
    except Exception as exc:
        logger.warning("site_zone: site_domains lookup failed domain=%s: %s", d, exc)
        return None
    return rows[0] if rows else None


def resolve_mode(db, org_id: str, domain: str, requested: Optional[str] = None) -> str:
    """Which flow a domain uses: what staff asked for, else what site_domains remembers, else whether the
    domain already has a zone in our Cloudflare account, else the client-CNAME flow."""
    if requested in (MODE_ZONE, MODE_CNAME):
        return requested
    row = _domain_row(db, org_id, domain)
    if row and row.get("dns_mode") == MODE_ZONE:
        return MODE_ZONE
    return MODE_ZONE if existing_zone(domain) else MODE_CNAME


def save_state(db, org_id: str, domain: str, info: dict) -> None:
    """Remembers the zone on the domain's site_domains row (when it has one). Never raises."""
    try:
        row = _domain_row(db, org_id, domain)
        if not row:
            return
        from datetime import datetime, timezone
        db.table("site_domains").update({
            "dns_mode": MODE_ZONE, "cf_zone_id": info.get("zone_id"), "cf_zone_status": info.get("zone_status"),
            "cf_nameservers": info.get("nameservers") or None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row["id"]).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.warning("site_zone: saving zone state failed domain=%s: %s", domain, exc)
