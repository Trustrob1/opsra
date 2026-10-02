"""
app/services/site_backup_service.py
------------------------------------
SITE-BACKUP — nightly offsite copy of every published client site, from Cloudflare R2
(bucket `opsra-sites`) to a second, independent S3-compatible bucket.

Why a separate destination: a backup that lives in the same account as the live sites is lost
with it if that account is suspended or a token is misused. Point BACKUP_S3_* at a bucket in a
DIFFERENT account or provider (for example a second Cloudflare account under another email,
or Backblaze B2, IDrive e2, Wasabi...). The same boto3 code works for any S3-compatible
endpoint, so the destination is just the BACKUP_S3_* settings.

Layout in the backup bucket:
    snapshots/<domain>/<yyyy-mm-dd>/<path as in R2>

How a run works (run_backup):
- Lists the whole R2 bucket and groups the keys by domain folder.
- For each domain, builds a manifest hash from the sorted (path, ETag, size) list. When it is
  identical to the last good backup of that domain AND that snapshot is still in the backup
  bucket, nothing is copied ("unchanged"). Otherwise the whole folder (a site is small) is
  copied into a new dated snapshot and then LISTED BACK: the key set and sizes must match the
  source, or the site is recorded as failed. A backup that was never checked is not a backup.
- Keeps the newest `keep` snapshots per domain and deletes older ones. A domain that has
  disappeared from R2 (unpublished or lapsed) keeps its snapshots for ORPHAN_KEEP_DAYS days.
  Pruning is skipped entirely when the R2 listing came back empty (a broken listing must
  never look like "everything was deleted").
- Writes one site_backup_runs row per run and one site_backup_items row per site.

SITE-STANDBY: prepare_backup_host() copies a snapshot to live/<domain>/ INSIDE THE BACKUP BUCKET so a
second copy of the sites Worker (cloudflare/sites-worker/wrangler.backup.toml, in the backup Cloudflare
account, SITE_PREFIX=live/) can serve the site if the main account is down. It reads only the backup
bucket and never touches R2 or DNS; pointing a domain at the standby is a manual step.

Rules:
- Never writes or deletes anything in R2 during a backup. restore_site_from_backup is the
  only function here that writes to R2, and it only touches `<domain>/`.
- Every domain has its own try/except (S14): one bad site never stops the others.
- Credentials come from the environment (BACKUP_S3_*). With any missing, a run is recorded as
  failed with a clear message instead of failing deep inside boto3.
- Alerts are sent by the worker (workers/site_worker.py), not here.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.services import site_publish_service as sp

logger = logging.getLogger(__name__)

SNAPSHOT_ROOT = "snapshots"
LIVE_ROOT = "live"               # what the standby Worker serves (SITE-STANDBY)
DEFAULT_KEEP = 14                # newest snapshots kept per domain
ORPHAN_KEEP_DAYS = 90            # a domain no longer in R2 keeps its snapshots this long
RUNNING_GUARD_HOURS = 3          # a 'running' row younger than this blocks a second run
MISSED_RUN_HOURS = 26            # watchdog: no run started in this long = a problem

_DOMAIN_RE = re.compile(r"^[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})+$")
_B2_REGION_RE = re.compile(r"^https?://s3\.([a-z0-9-]+)\.backblazeb2\.com", re.I)
_R2_ENDPOINT_RE = re.compile(r"^https?://[a-z0-9]+(\.[a-z0-9-]+)?\.r2\.cloudflarestorage\.com", re.I)


class BackupError(Exception):
    """Something went wrong copying one site (or the whole run)."""


class BackupNotConfigured(BackupError):
    """BACKUP_S3_* settings are missing."""


# ───────────────────────────────── clients ─────────────────────────────────

def _settings():
    from app.config import get_settings
    return get_settings()


def make_backup_client():
    """boto3 S3 client for the backup provider. Raises BackupNotConfigured when settings are missing."""
    s = _settings()
    endpoint = (s.BACKUP_S3_ENDPOINT or "").strip()
    if not (endpoint and s.BACKUP_S3_ACCESS_KEY_ID and s.BACKUP_S3_SECRET_ACCESS_KEY and s.BACKUP_S3_BUCKET):
        raise BackupNotConfigured(
            "Backups aren't set up yet. Add the BACKUP_S3_ENDPOINT, BACKUP_S3_ACCESS_KEY_ID, "
            "BACKUP_S3_SECRET_ACCESS_KEY and BACKUP_S3_BUCKET settings to the server.")
    region = backup_region(endpoint, s.BACKUP_S3_REGION)
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=s.BACKUP_S3_ACCESS_KEY_ID,
        aws_secret_access_key=s.BACKUP_S3_SECRET_ACCESS_KEY,
        region_name=region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def backup_region(endpoint: str, configured: Optional[str] = None) -> str:
    """The signing region for the backup endpoint. An explicit BACKUP_S3_REGION wins; otherwise
    Cloudflare R2 -> 'auto', Backblaze -> the region in the host name, anything else -> us-east-1."""
    region = (configured or "").strip()
    if region:
        return region
    if _R2_ENDPOINT_RE.match(endpoint or ""):
        return "auto"
    m = _B2_REGION_RE.match(endpoint or "")
    return m.group(1) if m else "us-east-1"


def _backup_bucket() -> str:
    return _settings().BACKUP_S3_BUCKET


def _keep() -> int:
    try:
        return max(1, int(_settings().BACKUP_KEEP_SNAPSHOTS))
    except Exception:
        return DEFAULT_KEEP


# ───────────────────────────────── helpers ─────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _clean_etag(etag: Any) -> str:
    return str(etag or "").strip('"')


def manifest_hash(entries: list) -> str:
    """entries = [(path, etag, size)]. Order-independent."""
    lines = sorted(f"{p}|{_clean_etag(e)}|{int(s)}" for p, e, s in entries)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def list_source_sites(client: Any, bucket: str) -> dict:
    """Lists the whole R2 bucket. Returns {domain: [(path, etag, size), ...]}.
    Keys that aren't under a valid domain folder are ignored."""
    sites: dict[str, list] = {}
    token = None
    while True:
        kwargs = {"Bucket": bucket}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for o in resp.get("Contents") or []:
            key = o.get("Key") or ""
            domain, sep, path = key.partition("/")
            if not sep or not path or path.endswith("/") or not _DOMAIN_RE.match(domain):
                continue
            sites.setdefault(domain, []).append((path, _clean_etag(o.get("ETag")), int(o.get("Size") or 0)))
        if not resp.get("IsTruncated"):
            return sites
        token = resp.get("NextContinuationToken")


def _snapshot_prefix(domain: str, day: Any) -> str:
    return f"{SNAPSHOT_ROOT}/{domain}/{day}/"


def _list_objects(client: Any, bucket: str, prefix: str) -> list:
    """[(key, size)] under a prefix."""
    out = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        out.extend((o["Key"], int(o.get("Size") or 0)) for o in resp.get("Contents") or [])
        if not resp.get("IsTruncated"):
            return out
        token = resp.get("NextContinuationToken")


def _common_prefixes(client: Any, bucket: str, prefix: str) -> list:
    """Immediate 'sub-folders' under a prefix, as full prefixes ending in '/'."""
    out = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix, "Delimiter": "/"}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        out.extend(p["Prefix"] for p in resp.get("CommonPrefixes") or [])
        if not resp.get("IsTruncated"):
            return out
        token = resp.get("NextContinuationToken")


def list_snapshot_dates(client: Any, bucket: str, domain: str) -> list:
    """Snapshot dates stored for a domain, newest first (as 'YYYY-MM-DD' strings)."""
    base = f"{SNAPSHOT_ROOT}/{domain}/"
    dates = []
    for p in _common_prefixes(client, bucket, base):
        d = p[len(base):].strip("/")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            dates.append(d)
    return sorted(dates, reverse=True)


def _snapshot_exists(client: Any, bucket: str, domain: str, day: Any) -> bool:
    resp = client.list_objects_v2(Bucket=bucket, Prefix=_snapshot_prefix(domain, day), MaxKeys=1)
    return bool(resp.get("Contents"))


def _delete_prefix(client: Any, bucket: str, prefix: str) -> int:
    """Deletes everything under a snapshot prefix. Refuses anything outside snapshots/."""
    if not prefix.startswith(SNAPSHOT_ROOT + "/") or len(prefix) <= len(SNAPSHOT_ROOT) + 1:
        raise BackupError(f"refusing to delete outside {SNAPSHOT_ROOT}/: {prefix!r}")
    keys = [k for k, _ in _list_objects(client, bucket, prefix)]
    for i in range(0, len(keys), 1000):
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True})
    return len(keys)


# ───────────────────────────────── one site ─────────────────────────────────

def backup_domain(src: Any, src_bucket: str, dst: Any, dst_bucket: str,
                  domain: str, entries: list, day: Any) -> dict:
    """Copies one site's files into snapshots/<domain>/<day>/ and verifies the copy.
    Returns {files, bytes}. Raises BackupError when the copy doesn't match the source."""
    prefix = _snapshot_prefix(domain, day)
    total = 0
    try:
        for path, etag, _size in sorted(entries, key=lambda e: e[0] == "index.html"):
            obj = src.get_object(Bucket=src_bucket, Key=f"{domain}/{path}")
            body = obj["Body"].read()
            kwargs = {"Bucket": dst_bucket, "Key": prefix + path, "Body": body, "Metadata": {"src-etag": etag}}
            if obj.get("ContentType"):
                kwargs["ContentType"] = obj["ContentType"]
            dst.put_object(**kwargs)
            total += len(body)
        stored = dict(_list_objects(dst, dst_bucket, prefix))
        # A re-run on the same day after the site changed can leave files from the earlier
        # copy behind. Remove them (only inside this snapshot folder) before checking.
        extras = [k for k in stored if k not in {prefix + p for p, _e, _s in entries}]
        if extras:
            for i in range(0, len(extras), 1000):
                dst.delete_objects(Bucket=dst_bucket, Delete={"Objects": [{"Key": k} for k in extras[i:i + 1000]], "Quiet": True})
            stored = {k: v for k, v in stored.items() if k not in set(extras)}
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f"copy failed: {exc}") from exc

    want = {prefix + p: int(s) for p, _e, s in entries}
    if stored != want:
        missing = len(set(want) - set(stored))
        wrong = sum(1 for k in set(want) & set(stored) if want[k] != stored[k])
        extra = len(set(stored) - set(want))
        raise BackupError(f"verification failed (missing {missing}, wrong size {wrong}, unexpected {extra})")
    return {"files": len(entries), "bytes": total}


# ───────────────────────────────── retention ─────────────────────────────────

def prune_snapshots(dst: Any, dst_bucket: str, live_domains: set, keep: int, today: date) -> int:
    """Deletes snapshots beyond the newest `keep` per domain, and the snapshots of a domain that
    has been gone from R2 for more than ORPHAN_KEEP_DAYS. Returns the number of snapshots deleted.
    Callers must not call this when the R2 listing was empty."""
    pruned = 0
    for dom_prefix in _common_prefixes(dst, dst_bucket, SNAPSHOT_ROOT + "/"):
        domain = dom_prefix[len(SNAPSHOT_ROOT) + 1:].strip("/")
        if not _DOMAIN_RE.match(domain):
            continue
        try:
            dates = list_snapshot_dates(dst, dst_bucket, domain)
            if domain in live_domains:
                doomed = dates[keep:]
            else:
                cutoff = (today - timedelta(days=ORPHAN_KEEP_DAYS)).isoformat()
                doomed = dates if (dates and dates[0] < cutoff) else []
            for d in doomed:
                _delete_prefix(dst, dst_bucket, _snapshot_prefix(domain, d))
                pruned += 1
        except Exception:  # S14
            logger.exception("[site_backup] prune failed domain=%s", domain)
    return pruned


# ───────────────────────────────── run records ─────────────────────────────────

def _last_good_item(db: Any, domain: str) -> Optional[dict]:
    rows = (db.table("site_backup_items").select("manifest_hash, snapshot_date, status")
            .eq("domain", domain).in_("status", ["backed_up", "unchanged"])
            .order("created_at", desc=True).limit(1).execute()).data
    return _one(rows)


def _running_recently(db: Any, now: datetime) -> bool:
    cutoff = (now - timedelta(hours=RUNNING_GUARD_HOURS)).isoformat()
    rows = (db.table("site_backup_runs").select("id").eq("status", "running")
            .gte("started_at", cutoff).limit(1).execute()).data
    return bool(rows)


def _insert_run(db: Any, now: datetime, trigger: str, status: str = "running", error: Optional[str] = None) -> str:
    row = {"trigger": trigger, "status": status, "started_at": now.isoformat()}
    if status != "running":
        row["finished_at"] = now.isoformat()
    if error:
        row["error"] = error[:1000]
    res = db.table("site_backup_runs").insert(row).execute()
    return _one(res.data)["id"]


# ───────────────────────────────── the run ─────────────────────────────────

def run_backup(db: Any, src: Any = None, dst: Any = None, src_bucket: Optional[str] = None,
               dst_bucket: Optional[str] = None, now: Optional[datetime] = None,
               trigger: str = "scheduled", keep: Optional[int] = None) -> dict:
    """One full backup pass. Returns a summary dict:
    {status, run_id, domains_total, domains_backed_up, domains_unchanged, domains_failed,
     files_copied, bytes_copied, snapshots_pruned, error, failures: [{domain, error}]}.
    Never raises for a per-site problem. status is 'skipped' when another run is in progress."""
    now = now or _now()
    summary = {"status": "ok", "run_id": None, "domains_total": 0, "domains_backed_up": 0,
               "domains_unchanged": 0, "domains_failed": 0, "files_copied": 0, "bytes_copied": 0,
               "snapshots_pruned": 0, "error": None, "failures": []}

    if _running_recently(db, now):
        summary["status"] = "skipped"
        summary["error"] = "another backup run is still in progress"
        return summary

    try:
        src = src or sp.make_client()
        src_bucket = src_bucket or sp._bucket()
        dst = dst or make_backup_client()
        dst_bucket = dst_bucket or _backup_bucket()
    except (BackupNotConfigured, sp.NotConfigured) as exc:
        summary.update(status="failed", error=str(exc))
        summary["run_id"] = _insert_run(db, now, trigger, "failed", str(exc))
        return summary
    except Exception as exc:  # S14
        summary.update(status="failed", error=f"could not connect: {exc}")
        summary["run_id"] = _insert_run(db, now, trigger, "failed", summary["error"])
        return summary

    run_id = _insert_run(db, now, trigger)
    summary["run_id"] = run_id
    keep = keep or _keep()
    day = now.date().isoformat()

    try:
        sites = list_source_sites(src, src_bucket)
    except Exception as exc:  # S14
        summary.update(status="failed", error=f"could not list the live sites: {exc}")
        _finish_run(db, run_id, summary, now)
        return summary

    summary["domains_total"] = len(sites)

    for domain in sorted(sites):
        entries = sites[domain]
        mhash = manifest_hash(entries)
        item = {"run_id": run_id, "domain": domain, "manifest_hash": mhash,
                "files": len(entries), "bytes": sum(e[2] for e in entries)}
        try:
            last = _last_good_item(db, domain)
            if (last and last.get("manifest_hash") == mhash and last.get("snapshot_date")
                    and _snapshot_exists(dst, dst_bucket, domain, last["snapshot_date"])):
                item.update(status="unchanged", snapshot_date=last["snapshot_date"], verified=True)
                summary["domains_unchanged"] += 1
            else:
                out = backup_domain(src, src_bucket, dst, dst_bucket, domain, entries, day)
                item.update(status="backed_up", snapshot_date=day, verified=True)
                summary["domains_backed_up"] += 1
                summary["files_copied"] += out["files"]
                summary["bytes_copied"] += out["bytes"]
        except Exception as exc:  # S14 — one site failing never stops the others
            msg = str(exc)[:500]
            logger.warning("[site_backup] domain=%s failed: %s", domain, msg)
            item.update(status="failed", error=msg, verified=False, files=0, bytes=0)
            summary["domains_failed"] += 1
            summary["failures"].append({"domain": domain, "error": msg})
        try:
            db.table("site_backup_items").insert(item).execute()
        except Exception:  # S14
            logger.exception("[site_backup] could not record item domain=%s", domain)

    # Retention — only when the listing looked healthy.
    if sites:
        try:
            summary["snapshots_pruned"] = prune_snapshots(dst, dst_bucket, set(sites), keep, now.date())
        except Exception:  # S14
            logger.exception("[site_backup] prune failed")

    if summary["domains_failed"] == 0:
        summary["status"] = "ok"
    elif summary["domains_failed"] < summary["domains_total"]:
        summary["status"] = "partial"
    else:
        summary["status"] = "failed"
    if summary["failures"]:
        first = summary["failures"][0]
        summary["error"] = f"{summary['domains_failed']} site(s) failed, e.g. {first['domain']}: {first['error']}"[:1000]

    _finish_run(db, run_id, summary, _now())
    logger.info("[site_backup] run=%s status=%s total=%d backed_up=%d unchanged=%d failed=%d pruned=%d",
                run_id, summary["status"], summary["domains_total"], summary["domains_backed_up"],
                summary["domains_unchanged"], summary["domains_failed"], summary["snapshots_pruned"])
    return summary


def _finish_run(db: Any, run_id: str, s: dict, finished: datetime) -> None:
    try:
        db.table("site_backup_runs").update({
            "status": s["status"], "finished_at": finished.isoformat(),
            "domains_total": s["domains_total"], "domains_backed_up": s["domains_backed_up"],
            "domains_unchanged": s["domains_unchanged"], "domains_failed": s["domains_failed"],
            "files_copied": s["files_copied"], "bytes_copied": s["bytes_copied"],
            "snapshots_pruned": s["snapshots_pruned"], "error": (s.get("error") or None),
        }).eq("id", run_id).execute()
    except Exception:  # S14
        logger.exception("[site_backup] could not finish run record run=%s", run_id)


# ───────────────────────────────── watchdog ─────────────────────────────────

def backup_problem(db: Any, now: Optional[datetime] = None) -> Optional[str]:
    """Returns a plain-English problem to alert on, or None when backups look healthy.
    Looks at the most recent run: missed (nothing started in MISSED_RUN_HOURS), failed or partial."""
    now = now or _now()
    last = _one((db.table("site_backup_runs").select("status, started_at, error")
                 .order("started_at", desc=True).limit(1).execute()).data)
    if not last:
        return "No site backup has ever run. Check that the BACKUP_S3_* settings are set and the beat service is running."
    started = _parse_iso(last.get("started_at"))
    if started and (now - started) > timedelta(hours=MISSED_RUN_HOURS):
        return f"The last site backup started more than {MISSED_RUN_HOURS} hours ago. The nightly job may not be running."
    if last.get("status") == "failed":
        return f"The last site backup failed: {last.get('error') or 'no detail recorded'}"
    if last.get("status") == "partial":
        return f"The last site backup copied most sites but not all: {last.get('error') or 'see the backup run record'}"
    return None


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ───────────────────────────────── restore ─────────────────────────────────

def restore_site_from_backup(domain: str, snapshot_date: Optional[str] = None,
                             src: Any = None, src_bucket: Optional[str] = None,
                             dst: Any = None, dst_bucket: Optional[str] = None) -> dict:
    """Copies a site from the backup bucket back into R2 under `<domain>/`.
    `snapshot_date` None = the newest snapshot. Images go first and index.html last, and files in
    R2 that aren't part of the snapshot are removed only after every upload succeeded (same
    safety as publishing). Returns {domain, snapshot_date, files, bytes, removed}.
    NOTE: argument names follow the direction of the data: `src` is the BACKUP bucket here,
    `dst` is R2."""
    d = sp.normalise_domain(domain)
    backup = src or make_backup_client()
    backup_bucket = src_bucket or _backup_bucket()
    r2 = dst or sp.make_client()
    r2_bucket = dst_bucket or sp._bucket()

    dates = list_snapshot_dates(backup, backup_bucket, d)
    if not dates:
        raise BackupError(f"No backup exists for {d}.")
    day = snapshot_date or dates[0]
    if day not in dates:
        raise BackupError(f"No backup of {d} for {day}. Available: {', '.join(dates[:5])}")

    prefix = _snapshot_prefix(d, day)
    objects = _list_objects(backup, backup_bucket, prefix)
    if not objects:
        raise BackupError(f"The {day} backup of {d} is empty.")

    r2_prefix = f"{d}/"
    new_keys: set = set()
    total = 0
    try:
        for key, _size in sorted(objects, key=lambda o: o[0][len(prefix):] == "index.html"):
            path = key[len(prefix):]
            body = backup.get_object(Bucket=backup_bucket, Key=key)["Body"].read()
            r2.put_object(Bucket=r2_bucket, Key=r2_prefix + path, Body=body,
                          ContentType=sp._content_type(path), CacheControl=sp._cache_control(path))
            new_keys.add(r2_prefix + path)
            total += len(body)
        stale = [k for k in sp._list_keys(r2, r2_bucket, r2_prefix) if k not in new_keys]
        removed = sp._delete_keys(r2, r2_bucket, stale, r2_prefix) if stale else 0
    except Exception as exc:
        raise BackupError(f"Restore of {d} failed part-way: {exc}. Run it again; nothing is removed until all files are uploaded.") from exc

    return {"domain": d, "snapshot_date": day, "files": len(new_keys), "bytes": total, "removed": removed}


# ───────────────────────────── standby host (SITE-STANDBY) ─────────────────────────────

def list_backed_up_domains(client: Any, bucket: str) -> list:
    base = SNAPSHOT_ROOT + "/"
    return sorted(p[len(base):].strip("/") for p in _common_prefixes(client, bucket, base)
                  if _DOMAIN_RE.match(p[len(base):].strip("/")))


def _prepare_one(client: Any, bucket: str, domain: str, snapshot_date: Optional[str]) -> dict:
    dates = list_snapshot_dates(client, bucket, domain)
    if not dates:
        raise BackupError(f"No backup exists for {domain}.")
    day = snapshot_date or dates[0]
    if day not in dates:
        raise BackupError(f"No backup of {domain} for {day}. Available: {', '.join(dates[:5])}")
    prefix = _snapshot_prefix(domain, day)
    objects = _list_objects(client, bucket, prefix)
    if not objects:
        raise BackupError(f"The {day} backup of {domain} is empty.")

    live_prefix = f"{LIVE_ROOT}/{domain}/"
    want: dict = {}
    try:
        for key, _size in sorted(objects, key=lambda o: o[0][len(prefix):] == "index.html"):
            path = key[len(prefix):]
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            client.put_object(Bucket=bucket, Key=live_prefix + path, Body=body,
                              ContentType=sp._content_type(path), CacheControl=sp._cache_control(path))
            want[live_prefix + path] = len(body)
        stored = dict(_list_objects(client, bucket, live_prefix))
        stale = [k for k in stored if k not in want]
        if stale:
            sp._delete_keys(client, bucket, stale, live_prefix)
            stored = {k: v for k, v in stored.items() if k in want}
    except Exception as exc:
        raise BackupError(f"copy failed part-way: {exc}. Run it again; the previous standby copy is only trimmed after every file is uploaded.") from exc
    if stored != want:
        raise BackupError(f"verification failed (missing {len(set(want) - set(stored))}, "
                          f"wrong size {sum(1 for k in set(want) & set(stored) if want[k] != stored[k])})")
    return {"domain": domain, "snapshot_date": day, "files": len(want), "bytes": sum(want.values()), "status": "ready"}


def prepare_backup_host(domain: Optional[str] = None, snapshot_date: Optional[str] = None,
                        client: Any = None, bucket: Optional[str] = None) -> dict:
    """Copies the newest (or chosen) snapshot of one site, or of every backed-up site when `domain`
    is None, to live/<domain>/ in the backup bucket and verifies it. Reads/writes only the backup
    bucket. One bad site never stops the others (S14). Returns {ok, results, failed}."""
    c = client or make_backup_client()
    b = bucket or _backup_bucket()
    if domain:
        domains = [sp.normalise_domain(domain)]
    else:
        domains = list_backed_up_domains(c, b)
        if not domains:
            raise BackupError("There are no backups yet, so there is nothing to prepare.")
    results, failed = [], []
    for d in domains:
        try:
            results.append(_prepare_one(c, b, d, snapshot_date))
        except Exception as exc:  # S14
            logger.warning("[site_backup] standby prepare failed for %s: %s", d, exc)
            failed.append({"domain": d, "status": "failed", "error": str(exc)[:300]})
    return {"ok": not failed, "results": results, "failed": failed}
