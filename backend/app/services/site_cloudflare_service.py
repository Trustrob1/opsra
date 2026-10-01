"""
app/services/site_cloudflare_service.py
----------------------------------------
SITE-HOSTNAMES — connect a client's own domain to the `opsra-sites` Worker with Cloudflare for SaaS
"custom hostnames", so nobody has to add each domain by hand in the Cloudflare dashboard.

Flow: the client (or whoever manages their domain) points a DNS record at SITES_CNAME_TARGET
(`sites.coreaicloudtech.com.ng`). We register the domain and its `www.` form as custom hostnames on the
SaaS zone; Cloudflare then verifies the DNS record and issues the SSL certificate by itself (HTTP
validation, so the client adds no extra TXT record). The Worker then serves the site by Host header.

Rules:
- Settings come from the environment (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID, SITES_CNAME_TARGET).
  With the token or zone missing the feature is "not set up": callers get NotConfigured and skip it.
- register_domain() is safe to repeat: a hostname that already exists is returned, never created twice.
- Cloudflare's error text is logged, never shown to staff (it can echo request details); staff get a
  plain message. The API token is never logged or returned.
- Errors are SiteOpsError subclasses so routers/sites.py `_ops()` maps them to 4xx/5xx.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.site_ops_service import SiteOpsError
from app.services.site_publish_service import normalise_domain

logger = logging.getLogger(__name__)

API_BASE = "https://api.cloudflare.com/client/v4"


class HostnameError(SiteOpsError):
    status_code = 502
    code = "HOSTNAMES_FAILED"


class HostnamesNotConfigured(HostnameError):
    status_code = 503
    code = "HOSTNAMES_NOT_CONFIGURED"


def _settings():
    from app.config import get_settings
    return get_settings()


class CloudflareClient:
    """Thin wrapper over the Cloudflare REST API. `request` returns the parsed JSON body and raises
    HostnameError on any failure. Tests replace this with a fake that has the same `request` method."""

    def __init__(self, token: str, timeout: float = 20.0):
        self._token = token
        self._timeout = timeout

    def request(self, method: str, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        import httpx
        try:
            resp = httpx.request(
                method, f"{API_BASE}{path}", json=json, params=params, timeout=self._timeout,
                headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            )
            body = resp.json()
        except Exception as exc:
            logger.warning("site_cloudflare: %s %s failed: %s", method, path, type(exc).__name__)
            raise HostnameError("Couldn't reach Cloudflare. Try again in a minute.")
        if resp.status_code >= 400 or not body.get("success", False):
            logger.warning("site_cloudflare: %s %s -> %s errors=%s", method, path, resp.status_code, body.get("errors"))
            raise HostnameError("Cloudflare didn't accept the request. Check the Cloudflare settings on the server and try again.")
        return body


def make_client() -> tuple:
    """Returns (client, zone_id, cname_target). Raises HostnamesNotConfigured when not set up."""
    s = _settings()
    token = getattr(s, "CLOUDFLARE_API_TOKEN", "")
    zone = getattr(s, "CLOUDFLARE_ZONE_ID", "")
    if not (token and zone):
        raise HostnamesNotConfigured("Automatic domain connection isn't set up yet. Add the Cloudflare settings to the server first.")
    return CloudflareClient(token), zone, (getattr(s, "SITES_CNAME_TARGET", "") or "sites.coreaicloudtech.com.ng")


def hostnames_for(domain: str) -> list:
    d = normalise_domain(domain)
    return [d, f"www.{d}"]


def _summary(row: dict) -> dict:
    ssl = row.get("ssl") or {}
    status = row.get("status") or "pending"
    ssl_status = ssl.get("status") or "initializing"
    return {
        "hostname": row.get("hostname"),
        "id": row.get("id"),
        "status": status,
        "ssl_status": ssl_status,
        "active": status == "active" and ssl_status == "active",
        "errors": [str(e) for e in (row.get("verification_errors") or [])][:3],
    }


def _find(client: Any, zone: str, hostname: str) -> Optional[dict]:
    body = client.request("GET", f"/zones/{zone}/custom_hostnames", params={"hostname": hostname})
    for row in body.get("result") or []:
        if str(row.get("hostname", "")).lower() == hostname:
            return row
    return None


def _create(client: Any, zone: str, hostname: str) -> dict:
    body = client.request("POST", f"/zones/{zone}/custom_hostnames", json={
        "hostname": hostname,
        "ssl": {"method": "http", "type": "dv", "settings": {"http2": "on", "min_tls_version": "1.2"}},
    })
    return body.get("result") or {"hostname": hostname}


def dns_instructions(domain: str, target: str) -> list:
    """The DNS records the client must add, in plain words."""
    d = normalise_domain(domain)
    return [
        {"host": f"www.{d}", "type": "CNAME", "value": target,
         "note": "Add this at wherever the domain's DNS is managed."},
        {"host": d, "type": "CNAME", "value": target,
         "note": "Only if the DNS provider allows a CNAME on the bare domain (called ALIAS or CNAME flattening). "
                 f"Otherwise forward {d} to www.{d} at the registrar."},
    ]


def register_domain(domain: str, client: Any = None, zone: Optional[str] = None, target: Optional[str] = None) -> dict:
    """Registers the domain and its www form (idempotent). Returns {domain, target, hostnames, dns, all_active}."""
    if client is None:
        client, zone, target = make_client()
    d = normalise_domain(domain)
    rows = []
    for host in hostnames_for(d):
        row = _find(client, zone, host) or _create(client, zone, host)
        rows.append(_summary(row))
    return {"domain": d, "target": target, "hostnames": rows, "dns": dns_instructions(d, target),
            "all_active": all(r["active"] for r in rows)}


def status_domain(domain: str, client: Any = None, zone: Optional[str] = None, target: Optional[str] = None) -> dict:
    """Current status of the domain's hostnames, without creating anything. A hostname Cloudflare doesn't
    know yet is reported as status 'not_registered'."""
    if client is None:
        client, zone, target = make_client()
    d = normalise_domain(domain)
    rows = []
    for host in hostnames_for(d):
        row = _find(client, zone, host)
        rows.append(_summary(row) if row else {"hostname": host, "id": None, "status": "not_registered",
                                               "ssl_status": "none", "active": False, "errors": []})
    return {"domain": d, "target": target, "hostnames": rows, "dns": dns_instructions(d, target),
            "all_active": all(r["active"] for r in rows)}


def remove_domain(domain: str, client: Any = None, zone: Optional[str] = None) -> dict:
    """Removes the domain's hostnames from Cloudflare (for example when a site lapses)."""
    if client is None:
        client, zone, _ = make_client()
    d = normalise_domain(domain)
    removed = 0
    for host in hostnames_for(d):
        row = _find(client, zone, host)
        if row and row.get("id"):
            client.request("DELETE", f"/zones/{zone}/custom_hostnames/{row['id']}")
            removed += 1
    return {"domain": d, "removed": removed}
