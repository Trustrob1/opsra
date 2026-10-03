"""
premium_import.py - SITE-PREMIUM P1: import a hand-written Premium skeleton into a site (no dashboard yet).

Run from the backend folder (Windows cmd or the Render Shell):
    python premium_import.py <site_id> <skeleton.html> [--headline "Outfit"] [--body "Hanken Grotesk"] [--check] [--visual] [--out preview.html]

  --check   validate only: runs the sanitiser, CSS contract, slot checks and a trial render, saves nothing.
  --visual  with --check: also render the page and measure it in a real browser (needs: pip install playwright,
            then: playwright install chromium). Screenshots go to premium-checks/<site_id>.
  --out F   also write the rendered preview page to file F so you can open it in a browser.

The org comes from the site row; the org must have site_builder_settings.premium_enabled = true.
Reads no .env itself: it uses the same environment variables the backend uses (python-dotenv loads them).
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Optional


def run(db: Any, site_id: str, html: str, headline: Optional[str] = None, body: Optional[str] = None,
        check_only: bool = False, out_path: Optional[str] = None, visual: bool = False) -> dict:
    from app.routers.sites import _log_event, _render_and_store
    from app.services import site_premium_service as svc

    site = (db.table("sites").select("*").eq("id", site_id).is_("deleted_at", "null").limit(1).execute()).data
    site = site[0] if isinstance(site, list) and site else (site or None)
    if not site:
        raise SystemExit(f"No site with id {site_id}")
    org_id = site["org_id"]
    settings = (db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data
    svc.require_enabled(settings[0] if isinstance(settings, list) and settings else settings)
    assets = (db.table("site_assets").select("id, public_url").eq("site_id", site_id).execute()).data or []
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in assets}
    from app.services import site_premium_fonts as fonts
    head, bod = headline or fonts.default_pair()[0], body or fonts.default_pair()[1]
    if check_only:
        parts = svc.validate_skeleton(html, site.get("content") or {}, head, bod, assets_by_id)
        result = {"ok": True, "saved": False, "removed": parts["removed"], "slots": len(parts["slot_manifest"]["slots"]),
                  "design_notes": parts.get("static_warnings", [])}
        if visual:
            from premium_visual_check import run as visual_run
            from app.services.site_premium_visual import VisualCheckUnavailable, summarise
            try:
                report = visual_run(db, site_id, html, head, bod)
                result["visual"] = summarise(report)
                result["ok"] = report["ok"]
            except VisualCheckUnavailable as exc:
                result["visual"] = f"NOT RUN: {exc}"
        return result
    result = svc.import_skeleton(db, org_id, site, "script:premium_import", html, head, bod, assets_by_id)
    site["tier"], site["current_design_id"] = "premium", result["id"]
    site = _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, "script:premium_import", "premium_design_imported",
               {"design_id": result["id"], "version": result["version"], "removed": len(result["removed"])})
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(site.get("rendered_html") or "")
    return {"ok": True, "saved": True, "design_id": result["id"], "version": result["version"],
            "removed": result["removed"], "preview_slug": site.get("slug"), "design_notes": result.get("warnings", [])}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Import a Premium skeleton into a site.")
    ap.add_argument("site_id")
    ap.add_argument("html_file")
    ap.add_argument("--headline")
    ap.add_argument("--body")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--visual", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    from app.database import get_supabase
    from app.services.site_ops_service import SiteOpsError
    with open(args.html_file, encoding="utf-8") as fh:
        html = fh.read()
    try:
        result = run(get_supabase(), args.site_id, html, args.headline, args.body, args.check, args.out, args.visual)
    except SiteOpsError as exc:
        print(f"NOT ACCEPTED: {exc}")
        return 1
    visual_text = result.pop("visual", None) if isinstance(result, dict) else None
    for note in (result.get("design_notes") or []) if isinstance(result, dict) else []:
        print("  design note: " + note)
    print(result)
    if visual_text:
        print(visual_text)
    return 0 if (not isinstance(result, dict) or result.get("ok", True)) else 1


if __name__ == "__main__":
    sys.exit(main())
