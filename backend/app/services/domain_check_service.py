"""
app/services/domain_check_service.py
-------------------------------------
SITE-3 — domain availability checks (spec §11.1).

  • Format check first (label length/characters, TLD in the org's configured
    list — pricing_service.get_settings' routes.standard/express.domains keys).
  • Availability at the REGISTRY:
      - gTLDs (.com, .net, .org, ...) via RDAP, through the public rdap.org
        bootstrap redirector (itself backed by the IANA bootstrap registry —
        spec explicitly calls out "via the IANA bootstrap").
      - .ng / .com.ng via NiRA's WHOIS (NiRA does not publish a public RDAP
        endpoint at time of writing; a raw WHOIS query to whois.nic.net.ng is
        used instead — spec §11.1 covers this under "NiRA's WHOIS/RDAP").
        NOTE FOR TRUST: the "taken" / "available" string match below
        (_NG_AVAILABLE_MARKERS / _NG_TAKEN_MARKERS) should be confirmed
        against one real registered .ng domain and one real available one
        before this is relied on for a live checkout — WHOIS response text
        varies by registry and isn't as strictly standardised as RDAP.
  • Express (SITE-3B) additionally checks Hostinger's own availability API —
    not implemented here yet (Express isn't enabled for any org yet).
  • Caching: 10 minutes, in-process (same non-durable pattern as the other
    in-process rate limiters in this codebase — resets on deploy/restart,
    acceptable for a cache whose only job is cutting down repeat registry
    hits within one short session).
  • Rate limit: 20 checks per builder per hour.
  • When taken: suggests up to 5 alternatives, each checked before being
    suggested (spec §11.1) — other supported endings, a hyphenated variant,
    and a "shop"/"get" prefix.

S14: check_domain() never raises for a registry lookup failure — it returns
status="unknown" for that one candidate instead, so one flaky RDAP/WHOIS
call never breaks the whole check. It DOES raise DomainCheckError for
caller mistakes (bad format, unsupported TLD, rate limit) — the router
converts those to 422/429.
"""
from __future__ import annotations

import logging
import re
import socket
import time
from collections import defaultdict
from typing import Any, Optional

import httpx

from app.services import pricing_service

logger = logging.getLogger(__name__)

_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

_CACHE_TTL_S = 10 * 60          # spec §11.1
_RATE_LIMIT_PER_HOUR = 20       # spec §11.1
_MAX_SUGGESTIONS = 5            # spec §11.1
_TLD_PREFERENCE_ORDER = [".ng", ".com.ng", ".com"]   # spec §11.1 order
_PREFIXES = ["shop", "get"]

_RDAP_UNIVERSAL = "https://rdap.org/domain/{domain}"
_NG_WHOIS_HOST = "whois.nic.net.ng"
_NG_WHOIS_PORT = 43
_NG_AVAILABLE_MARKERS = ("no match", "not found", "no entries found", "no data found", "is available")
_NG_TAKEN_MARKERS = ("domain name:", "registrant", "creation date", "registered on")

# In-process, non-durable — mirrors routers/builder_portal.py's _exchange_hits pattern.
_rate_hits: dict[str, list[float]] = defaultdict(list)
_cache: dict[str, tuple[float, dict]] = {}


class DomainCheckError(Exception):
    """Caller (router) maps this to a 4xx response."""


class RateLimited(DomainCheckError):
    pass


class InvalidDomain(DomainCheckError):
    pass


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

def _split_label_tld(domain: str, supported_tlds: list[str]) -> tuple[str, str]:
    """Longest-match against the org's configured TLDs, e.g. '.com.ng' before '.ng'."""
    d = (domain or "").strip().lower().rstrip(".")
    for tld in sorted(supported_tlds, key=len, reverse=True):
        if d.endswith(tld):
            label = d[: -len(tld)]
            return label, tld
    raise InvalidDomain(f"'{domain}' doesn't end in a supported ending ({', '.join(supported_tlds)}).")


def _validate_format(label: str, tld: str, supported_tlds: list[str]) -> None:
    if tld not in supported_tlds:
        raise InvalidDomain(f"'{tld}' isn't a supported ending.")
    if not label or not _LABEL_RE.match(label) or len(label) > 63:
        raise InvalidDomain("Domain names use only letters, digits and hyphens, and can't start or end with a hyphen.")


def _supported_tlds(settings: dict) -> list[str]:
    pricing = settings.get("pricing") or {}
    routes = pricing.get("routes") or {}
    tlds: set[str] = set()
    tlds.update((routes.get("standard") or {}).get("domains", {}).keys())
    if settings.get("express_enabled"):
        tlds.update((routes.get("express") or {}).get("domains", {}).keys())
    return sorted(tlds)


# ---------------------------------------------------------------------------
# Rate limit + cache
# ---------------------------------------------------------------------------

def _check_rate_limit(builder_id: str) -> None:
    now = _now()
    hits = [t for t in _rate_hits[builder_id] if now - t < 3600]
    if len(hits) >= _RATE_LIMIT_PER_HOUR:
        raise RateLimited("Too many domain checks this hour — try again later.")
    hits.append(now)
    _rate_hits[builder_id] = hits


def _cache_get(domain: str) -> Optional[dict]:
    hit = _cache.get(domain)
    if not hit:
        return None
    ts, value = hit
    if _now() - ts > _CACHE_TTL_S:
        _cache.pop(domain, None)
        return None
    return value


def _cache_set(domain: str, value: dict) -> None:
    _cache[domain] = (_now(), value)


# ---------------------------------------------------------------------------
# Registry lookups — each returns True (available) / False (taken) / None (unknown)
# ---------------------------------------------------------------------------

def _check_rdap_gtld(domain: str) -> Optional[bool]:
    try:
        with httpx.Client(timeout=8, follow_redirects=True) as client:
            resp = client.get(_RDAP_UNIVERSAL.format(domain=domain))
        if resp.status_code == 404:
            return True
        if resp.status_code == 200:
            return False
        logger.warning("RDAP check for %s returned unexpected status %s", domain, resp.status_code)
        return None
    except Exception as exc:
        logger.warning("RDAP check failed for %s: %s", domain, exc)
        return None


def _check_whois_ng(domain: str) -> Optional[bool]:
    try:
        with socket.create_connection((_NG_WHOIS_HOST, _NG_WHOIS_PORT), timeout=6) as sock:
            sock.sendall((domain + "\r\n").encode("ascii"))
            chunks = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        text = b"".join(chunks).decode(errors="ignore").lower()
        if any(m in text for m in _NG_AVAILABLE_MARKERS):
            return True
        if any(m in text for m in _NG_TAKEN_MARKERS):
            return False
        logger.warning("NiRA WHOIS response for %s didn't match a known pattern — treating as unknown", domain)
        return None
    except Exception as exc:
        logger.warning("NiRA WHOIS check failed for %s: %s", domain, exc)
        return None


def _lookup_availability(domain: str, tld: str) -> Optional[bool]:
    if tld in (".ng", ".com.ng"):
        return _check_whois_ng(domain)
    return _check_rdap_gtld(domain)


def _check_one(domain: str, tld: str) -> dict:
    """Cached, single-domain availability check. Never raises."""
    cached = _cache_get(domain)
    if cached is not None:
        return cached
    available = _lookup_availability(domain, tld)
    result = {
        "domain": domain,
        "status": "available" if available is True else ("taken" if available is False else "unknown"),
        "available": bool(available) if available is not None else None,
    }
    _cache_set(domain, result)
    return result


# ---------------------------------------------------------------------------
# Suggestions — spec §11.1: other endings, a hyphen, a "shop"/"get" prefix
# ---------------------------------------------------------------------------

def _hyphenate(label: str) -> Optional[str]:
    """Approximate — there's no word-boundary info in a bare label, so this
    splits roughly at the midpoint. Good enough as a suggestion, not a
    guarantee of a sensible word break."""
    if "-" in label or len(label) < 4:
        return None
    mid = len(label) // 2
    return f"{label[:mid]}-{label[mid:]}"


def _candidate_list(label: str, tld: str, supported_tlds: list[str]) -> list[str]:
    candidates: list[str] = []

    def add(cand: str) -> None:
        if cand not in candidates and cand != f"{label}{tld}":
            candidates.append(cand)

    # 1) other supported endings, same label, in spec's preference order
    for alt_tld in _TLD_PREFERENCE_ORDER:
        if alt_tld != tld and alt_tld in supported_tlds:
            add(f"{label}{alt_tld}")
    for alt_tld in supported_tlds:
        if alt_tld not in _TLD_PREFERENCE_ORDER and alt_tld != tld:
            add(f"{label}{alt_tld}")

    # 2) a hyphenated variant, original + other endings
    hyphenated = _hyphenate(label)
    if hyphenated:
        add(f"{hyphenated}{tld}")
        for alt_tld in _TLD_PREFERENCE_ORDER:
            if alt_tld != tld and alt_tld in supported_tlds:
                add(f"{hyphenated}{alt_tld}")

    # 3) a "shop"/"get" prefix, original ending
    for prefix in _PREFIXES:
        add(f"{prefix}{label}{tld}")

    return candidates


def _suggest_alternatives(label: str, tld: str, supported_tlds: list[str]) -> list[dict]:
    suggestions: list[dict] = []
    for candidate in _candidate_list(label, tld, supported_tlds):
        if len(suggestions) >= _MAX_SUGGESTIONS:
            break
        cand_label, cand_tld = _split_label_tld_safe(candidate, supported_tlds)
        if cand_label is None:
            continue
        result = _check_one(candidate, cand_tld)
        if result["available"]:
            suggestions.append(result)
    return suggestions


def _split_label_tld_safe(domain: str, supported_tlds: list[str]) -> tuple[Optional[str], Optional[str]]:
    try:
        return _split_label_tld(domain, supported_tlds)
    except InvalidDomain:
        return None, None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def check_domain(db: Any, org_id: str, builder_id: str, domain: str) -> dict:
    """
    Returns:
      {
        "domain", "status": "available"|"taken"|"unknown", "available": bool|None,
        "alternatives": [ {"domain", "status", "available"}, ... ]  # only when taken
      }
    Raises RateLimited / InvalidDomain — router converts to 429/422.
    """
    _check_rate_limit(builder_id)

    settings = pricing_service.get_settings(db, org_id)
    supported_tlds = _supported_tlds(settings)
    if not supported_tlds:
        raise InvalidDomain("No domain endings are configured for this organisation yet.")

    label, tld = _split_label_tld(domain, supported_tlds)
    _validate_format(label, tld, supported_tlds)
    normalised = f"{label}{tld}"

    result = _check_one(normalised, tld)
    if result["status"] != "available":
        result = dict(result)
        result["alternatives"] = _suggest_alternatives(label, tld, supported_tlds)
    return result
