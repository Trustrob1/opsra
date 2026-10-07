"""
site_import.py - SITE-IMPORT 1a: upload a finished single-page site (a .zip or one .html file) into a site.

Run from the backend folder (Windows cmd or the Render Shell):
    python site_import.py <site_id> <site.zip|page.html> [--check] [--accept "js/vendor.js:eval,dynamic_script_element"] [--json report.json]

  --check   analyse only: reads, scans and cleans the upload and prints the report. Saves nothing.
  --accept  staff accept named OVERRIDABLE findings for one file (repeat the flag for more files).
            A finding that is not overridable (cookies, unlisted hosts, miners...) can only be fixed in the file.
  --json F  also write the full report to file F.

Saves a NEW design version on the site (kind 'import', staged). It does not make it live and does not change
the site's tier: the preview and the switch arrive in IMPORT-1b.
The org comes from the site row; the org must have site_builder_settings.site_import_enabled = true.
Reads no .env itself: it uses the same environment variables the backend uses (python-dotenv loads them).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional


def parse_accept(items: Optional[list]) -> dict:
    out: dict = {}
    for item in items or []:
        path, _, rules = item.partition(":")
        out.setdefault(path.strip(), []).extend(r.strip() for r in rules.split(",") if r.strip())
    return out


def run(db: Any, site_id: str, data: bytes, filename: str, check_only: bool = False, accepted: Optional[dict] = None) -> dict:
    from app.services import site_import_service as svc

    site = (db.table("sites").select("*").eq("id", site_id).is_("deleted_at", "null").limit(1).execute()).data
    site = site[0] if isinstance(site, list) and site else (site or None)
    if not site:
        raise SystemExit(f"No site with id {site_id}")
    org_id = site["org_id"]
    settings = (db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data
    settings = settings[0] if isinstance(settings, list) and settings else settings
    result = svc.import_site(db, org_id, site, "script:site_import", data, filename, settings,
                             accepted=accepted, dry_run=check_only)
    if result.get("saved"):
        try:
            db.table("site_events").insert({"org_id": org_id, "site_id": site_id, "actor": "script:site_import",
                                            "event": "site_imported", "detail": {"design_id": result["design_id"],
                                                                                 "version": result["version"]}}).execute()
        except Exception:  # S14 - the event is an audit extra, never a reason to fail
            pass
    return result


def summarise(report: dict) -> str:
    c = report["counts"]
    lines = [f"Entry page: {report['entry']}",
             f"Files: {c['files']} ({c['bytes'] / 1024:.0f} KB): {c['css']} css, {c['js']} js, {c['image']} images, {c['font']} fonts",
             f"Scripts: {len(report['scripts'])} file(s) + {report['page'].get('inline_scripts', 0)} inline; "
             f"handlers: {report['page'].get('handlers', 0)}; forms: {report['page'].get('forms', 0)}"]
    for label, items in (("ERRORS", report["errors"]), ("Warnings", report["warnings"])):
        if items:
            lines.append(f"{label} ({len(items)}):")
            for f in items[:40]:
                tag = " [overridable]" if f.get("overridable") and f["severity"] == "error" else ""
                lines.append(f"  - {f['file']} line {f['line']}: {f['message']}{tag}" + (f"  <{f['snippet']}>" if f.get("snippet") else ""))
    if report["external"]["unknown"]:
        lines.append("Unlisted external files (not downloaded, will be blocked live):")
        lines += [f"  - {u['url']} ({u['tag']})" for u in report["external"]["unknown"][:20]]
    if report["missing_files"]:
        lines.append("Missing from the upload: " + ", ".join(report["missing_files"][:20]))
    if report["unreferenced"]:
        lines.append("Not used by the page: " + ", ".join(report["unreferenced"][:20]))
    if report["skipped"]:
        lines.append("Skipped file types: " + ", ".join(report["skipped"][:20]))
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Import a finished single-page site into a site.")
    ap.add_argument("site_id")
    ap.add_argument("upload")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--accept", action="append")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    from app.database import get_supabase
    from app.services import site_import_service as svc
    with open(args.upload, "rb") as fh:
        data = fh.read()
    try:
        result = run(get_supabase(), args.site_id, data, args.upload, args.check, parse_accept(args.accept))
    except svc.ImportRejected as exc:
        print("NOT ACCEPTED:")
        for e in exc.errors:
            print("  - " + e)
        if exc.report and args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(exc.report, fh, indent=2)
        return 1
    except svc.ImportFailed as exc:
        print(f"FAILED: {exc}")
        return 2
    print(summarise(result["report"]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result["report"], fh, indent=2)
    if result.get("saved"):
        print(f"\nSAVED design version {result['version']} (id {result['design_id']}), {result['files']} files. Not live yet.")
    else:
        print("\nChecked only. Nothing was saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
