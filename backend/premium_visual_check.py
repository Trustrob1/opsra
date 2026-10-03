"""
premium_visual_check.py - SITE-PREMIUM P1b: measure a Premium page in a real browser at 390, 1024 and 1440 px.

Run from the backend folder (Windows cmd):
    python premium_visual_check.py <site_id>                      checks the site's CURRENT Premium design
    python premium_visual_check.py <site_id> --skeleton F.html    checks a skeleton file BEFORE you import it (saves nothing)
        [--headline "Bodoni Moda"] [--body "Hanken Grotesk"]
    add  --out-dir DIR   to choose where the screenshots and report.json go (default: premium-checks\\<site_id>)

It renders the page with the site's real content and photos, then reports: sideways scrolling, text running off
the screen, text overlapping text, text lying over a photo, text clipped by its box, collapsed photo frames, an
oversized nav, a tiny phone headline and large empty gaps. Exit code 0 = no errors, 1 = errors found, 2 = the
browser part is not installed (pip install playwright, then: playwright install chromium).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional


def build_page(db: Any, site_id: str, skeleton_html: Optional[str] = None, headline: Optional[str] = None,
               body: Optional[str] = None) -> tuple[str, dict]:
    """(rendered page html, extra info). Reads the site; never writes anything."""
    from app.services import site_premium_fonts as fonts
    from app.services import site_premium_renderer as renderer
    from app.services import site_premium_service as svc

    rows = (db.table("sites").select("*").eq("id", site_id).is_("deleted_at", "null").limit(1).execute()).data
    site = rows[0] if isinstance(rows, list) and rows else (rows or None)
    if not site:
        raise SystemExit(f"No site with id {site_id}")
    assets = (db.table("site_assets").select("id, public_url").eq("site_id", site_id).execute()).data or []
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in assets}
    content = site.get("content") or {}
    if skeleton_html is not None:
        head, bod = headline or fonts.default_pair()[0], body or fonts.default_pair()[1]
        design = svc.validate_skeleton(skeleton_html, content, head, bod, assets_by_id)
        info = {"source": "skeleton file", "static_warnings": design.get("static_warnings", [])}
    else:
        if not site.get("current_design_id"):
            raise SystemExit("This site has no current Premium design. Import one first, or pass --skeleton FILE.")
        design = (db.table("site_designs").select("*").eq("id", site["current_design_id"]).eq("org_id", site["org_id"])
                  .limit(1).execute()).data
        design = design[0] if isinstance(design, list) and design else design
        if not design:
            raise SystemExit("The current design could not be read.")
        info = {"source": f"current design version {design.get('version')}",
                "static_warnings": ((design.get("checks") or {}).get("static") or {}).get("warnings", [])}
    page = renderer.render_premium_page(content=content, design=design, assets_by_id=assets_by_id, export=False)
    return page, info


def run(db: Any, site_id: str, skeleton_html: Optional[str] = None, headline: Optional[str] = None,
        body: Optional[str] = None, out_dir: Optional[str] = None) -> dict:
    from app.services import site_premium_visual as visual
    page, info = build_page(db, site_id, skeleton_html, headline, body)
    out_dir = out_dir or os.path.join("premium-checks", site_id)
    report = visual.run_visual_check(page, screenshot_dir=out_dir, label="page")
    report["info"].update(info)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(os.path.join(out_dir, "page.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    return report


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Measure a Premium page in a real browser.")
    ap.add_argument("site_id")
    ap.add_argument("--skeleton")
    ap.add_argument("--headline")
    ap.add_argument("--body")
    ap.add_argument("--out-dir")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    from app.database import get_supabase
    from app.services.site_ops_service import SiteOpsError
    from app.services.site_premium_visual import VisualCheckUnavailable, summarise
    html = None
    if args.skeleton:
        with open(args.skeleton, encoding="utf-8") as fh:
            html = fh.read()
    try:
        report = run(get_supabase(), args.site_id, html, args.headline, args.body, args.out_dir)
    except VisualCheckUnavailable as exc:
        print(f"CANNOT RUN: {exc}")
        return 2
    except SiteOpsError as exc:
        print(f"NOT ACCEPTED: {exc}")
        return 1
    for w in report["info"].get("static_warnings", []):
        print("  design note: " + w)
    print(summarise(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
