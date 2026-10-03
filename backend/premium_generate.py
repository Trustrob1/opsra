"""
premium_generate.py - SITE-PREMIUM P2: have Claude design a Premium site for one existing site (no dashboard UI yet).

Run from the backend folder (Windows cmd or the Render Shell):
    python premium_generate.py <site_id> [--out preview.html]

It runs the SAME job the worker runs (guards, art direction, build, checks, save), but in this process, so you
see the result straight away. It spends real money (one generation, about the cost shown at the end) and counts
toward the builder's daily limit and the org's daily cost cap. The org must have premium_enabled = true.
On success the site is switched to the new Premium design and its preview is re-rendered; on failure the site is
left exactly as it was and the reasons are printed. Reads no .env itself (python-dotenv loads it).
"""
from __future__ import annotations

import argparse
import json
import sys


def run(db, site_id: str, out_path=None) -> dict:
    from app.services import site_premium_generation_service as gen

    site = (db.table("sites").select("*").eq("id", site_id).is_("deleted_at", "null").limit(1).execute()).data
    site = site[0] if isinstance(site, list) and site else (site or None)
    if not site:
        raise SystemExit(f"No site with id {site_id}")
    row = gen.start_generation(db, site["org_id"], site, "script:premium_generate")
    print(f"Designing version {row['version']} with {row['model']} ... (1 to 4 minutes)")
    out = gen.run_generation(db, row["id"])
    if out.get("ok") and out_path:
        html = (db.table("sites").select("rendered_html").eq("id", site_id).limit(1).execute()).data
        html = (html[0] if isinstance(html, list) and html else html or {}).get("rendered_html") or ""
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(html)
    return out


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from app.database import get_supabase

    ap = argparse.ArgumentParser()
    ap.add_argument("site_id")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    result = run(get_supabase(), a.site_id, a.out)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result.get("ok") else 1)
