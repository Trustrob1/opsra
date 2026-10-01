"""
app/services/site_publish_service.py
-------------------------------------
SITE-PUBLISH — publish a client's site to Cloudflare R2, where the `opsra-sites` Worker
serves it by domain name (cloudflare/sites-worker).

What it does: builds the same files as the export zip (site_ops_service.collect_export_files),
uploads them to the R2 bucket under a folder named after the client's domain
(`<domain>/index.html`, `<domain>/images/...`), then removes files in that folder that are no
longer part of the site. Publishing again replaces the site — it is safe to repeat.

Rules:
- The folder is the domain WITHOUT a leading "www." (the Worker does the same), so
  `www.shop.com` and `shop.com` serve one site.
- Images and other files go up first and index.html goes last, so a visitor never sees a
  page that points at images that aren't there yet.
- Stale-file cleanup only ever touches keys under `<domain>/`, and only after every upload
  succeeded. A failed upload leaves the previous version exactly as it was.
- Credentials come from the environment (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
  R2_SECRET_ACCESS_KEY, R2_BUCKET). With any of them missing, publishing reports a clear
  "not set up" error instead of failing deep inside boto3.
- Errors are SiteOpsError subclasses so routers/sites.py `_ops()` turns them into 4xx/5xx.
"""
from __future__ import annotations

import logging
import mimetypes
import re
from typing import Any, Optional

from app.services import site_ops_service
from app.services.site_ops_service import SiteOpsError

logger = logging.getLogger(__name__)

_DOMAIN_RE = re.compile(r"^[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})+$")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_PAGE_CACHE = "public, max-age=60"          # pages: an edit shows up within a minute
_FILE_CACHE = "public, max-age=3600"        # images


class PublishError(SiteOpsError):
    status_code = 502
    code = "PUBLISH_FAILED"


class NotConfigured(PublishError):
    status_code = 503
    code = "PUBLISH_NOT_CONFIGURED"


class NoDomain(PublishError):
    status_code = 422
    code = "VALIDATION_ERROR"


def normalise_domain(domain: Optional[str]) -> str:
    """'https://WWW.Shop.com.ng/' -> 'shop.com.ng'. Raises NoDomain when it isn't a plausible domain."""
    d = (domain or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0].split("?")[0].rstrip(".")
    if d.startswith("www."):
        d = d[4:]
    if not _DOMAIN_RE.match(d):
        raise NoDomain("This site has no valid domain yet. Add a domain to its order before publishing.")
    return d


def _content_type(path: str) -> str:
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _CONTENT_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def _cache_control(path: str) -> str:
    return _PAGE_CACHE if path.endswith((".html", ".txt", ".xml")) else _FILE_CACHE


def _settings():
    from app.config import get_settings
    return get_settings()


def make_client():
    """boto3 S3 client pointed at R2. Raises NotConfigured when credentials aren't set."""
    s = _settings()
    if not (s.R2_ACCOUNT_ID and s.R2_ACCESS_KEY_ID and s.R2_SECRET_ACCESS_KEY and s.R2_BUCKET):
        raise NotConfigured("Publishing isn't set up yet. Add the Cloudflare R2 settings to the server first.")
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=f"https://{s.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=s.R2_ACCESS_KEY_ID,
        aws_secret_access_key=s.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def _bucket() -> str:
    return _settings().R2_BUCKET


def _list_keys(client: Any, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        keys.extend(o["Key"] for o in resp.get("Contents") or [])
        if not resp.get("IsTruncated"):
            return keys
        token = resp.get("NextContinuationToken")


def _delete_keys(client: Any, bucket: str, keys: list[str], prefix: str) -> int:
    """Deletes keys in batches of 1000. Refuses anything outside `prefix` (defence in depth)."""
    safe = [k for k in keys if prefix and k.startswith(prefix) and len(k) > len(prefix)]
    for i in range(0, len(safe), 1000):
        batch = safe[i:i + 1000]
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True})
    return len(safe)


def _ordered(files: list) -> list:
    """Everything else first, index.html last."""
    return sorted(files, key=lambda f: f[0] == "index.html")


def site_domain(db: Any, org_id: str, site_id: str) -> str:
    """The normalised domain of a site's latest non-expired order. Raises NotFound / NoDomain."""
    site = site_ops_service._one((db.table("sites").select("id").eq("id", site_id).eq("org_id", org_id)
                                  .is_("deleted_at", "null").limit(1).execute()).data)
    if not site:
        raise site_ops_service.NotFound("Site not found")
    order = site_ops_service._one((db.table("site_orders").select("domain").eq("org_id", org_id).eq("site_id", site_id)
                                   .neq("status", "expired").order("created_at", desc=True).limit(1).execute()).data)
    return normalise_domain((order or {}).get("domain"))


def publish_site(db: Any, org_id: str, site_id: str, client: Any = None, bucket: Optional[str] = None) -> dict:
    """Uploads the site to R2. Returns {domain, prefix, files, bytes, removed, urls}.
    Raises NotFound / ValidationFailed (from the export), NoDomain, NotConfigured, PublishError."""
    files, _site, order_domain = site_ops_service.collect_export_files(db, org_id, site_id)
    domain = normalise_domain(order_domain)
    prefix = f"{domain}/"

    client = client or make_client()
    bucket = bucket or _bucket()

    total = 0
    new_keys: set[str] = set()
    try:
        for path, data in _ordered(files):
            body = data.encode("utf-8") if isinstance(data, str) else data
            key = prefix + path
            client.put_object(Bucket=bucket, Key=key, Body=body,
                              ContentType=_content_type(path), CacheControl=_cache_control(path))
            new_keys.add(key)
            total += len(body)
        stale = [k for k in _list_keys(client, bucket, prefix) if k not in new_keys]
        removed = _delete_keys(client, bucket, stale, prefix) if stale else 0
    except SiteOpsError:
        raise
    except Exception as exc:  # botocore ClientError, network errors…
        logger.warning("site_publish: upload failed site=%s domain=%s: %s", site_id, domain, exc)
        raise PublishError("Cloudflare storage didn't accept the upload. Nothing was changed on the live site. Try again in a minute.")

    logger.info("site_publish: site=%s domain=%s files=%d bytes=%d removed=%d", site_id, domain, len(new_keys), total, removed)
    return {
        "domain": domain, "prefix": prefix, "files": len(new_keys), "bytes": total, "removed": removed,
        "urls": [f"https://{domain}/", f"https://www.{domain}/"],
    }


def unpublish_domain(domain: str, client: Any = None, bucket: Optional[str] = None) -> dict:
    """Removes every file stored for a domain (for example when a site lapses). Returns {domain, removed}."""
    d = normalise_domain(domain)
    prefix = f"{d}/"
    client = client or make_client()
    bucket = bucket or _bucket()
    try:
        removed = _delete_keys(client, bucket, _list_keys(client, bucket, prefix), prefix)
    except SiteOpsError:
        raise
    except Exception as exc:
        logger.warning("site_publish: unpublish failed domain=%s: %s", d, exc)
        raise PublishError("Cloudflare storage didn't accept the change. Try again in a minute.")
    return {"domain": d, "removed": removed}
