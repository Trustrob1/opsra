"""
premium_golden.py - SITE-PREMIUM P2: run the golden set (spec section 14). Generates a Premium design for each of
the 10 fictional briefs in premium_golden_briefs.py, WITHOUT touching the database, and writes everything to a folder
so the designs can be reviewed by eye (and with design:design-critique / design:accessibility-review).

Run from the backend folder:
    python premium_golden.py [--only boutique,salon] [--out premium-golden] [--model claude-sonnet-5-5] [--dry]

  --dry   do not call Claude: prints each brief's validation result and exits (checks the briefs themselves).
Outputs per brief in <out>/<key>/: page.html (the rendered page), art_direction.json, report.json (usage, cost, checks).
Plus <out>/summary.json: pass rate, average cost, average attempts. Reads no .env itself (python-dotenv loads it).
Each full run costs real money (about the same as ten generations): run it deliberately.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


def run(only=None, out_dir="premium-golden", model="claude-sonnet-5-5", dry=False, claude=None):
    from app.models.sites import SiteContentV1
    from app.services import site_premium_fonts as fonts
    from app.services import site_premium_generation_service as gen
    from app.services import site_premium_renderer as renderer
    from premium_golden_briefs import BRIEFS

    claude = claude or gen.call_claude_checked
    os.makedirs(out_dir, exist_ok=True)
    rows, fingerprints = [], []
    for b in BRIEFS:
        if only and b["key"] not in only:
            continue
        content = SiteContentV1.model_validate(b["content"]).model_dump()
        if dry:
            rows.append({"key": b["key"], "ok": True, "dry": True, "niche_fonts": list(fonts.NICHE_HEADLINES.get(b["key"], ()))[:3]})
            continue
        started = time.monotonic()
        result = gen.design_site(content=content, brief={"personality": b["personality"]}, niche=b["key"], personality=b["personality"],
                                 assets=[], assets_by_id={}, design_notes="", do_not_repeat=list(fingerprints[-12:]), model=model, claude=claude)
        usage = result["usage"]
        cost = gen.cost_usd(model, usage.input_tokens, usage.output_tokens)
        folder = os.path.join(out_dir, b["key"])
        os.makedirs(folder, exist_ok=True)
        report = {"key": b["key"], "ok": result["ok"], "cost_usd": cost, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                  "attempts": result["attempts"], "seconds": round(time.monotonic() - started, 1)}
        if result["ok"]:
            art, parts = result["art"], result["parts"]
            design = {"skeleton_html": parts["skeleton_html"], "skeleton_css": parts["skeleton_css"], "tokens": parts["tokens"], "art_direction": art}
            page = renderer.render_premium_page(content=content, design=design, assets_by_id={}, export=False)
            with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as fh:
                fh.write(page)
            with open(os.path.join(folder, "art_direction.json"), "w", encoding="utf-8") as fh:
                json.dump(art, fh, indent=2)
            report["warnings"] = result["warnings"] + parts["static_warnings"]
            fingerprints.append(gen.prompt.fingerprint(art))
        else:
            report.update({"stage": result["stage"], "errors": result["errors"]})
        with open(os.path.join(folder, "report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        rows.append(report)
        print(f"{b['key']:<13} {'PASS' if report['ok'] else 'FAIL'}  ${cost:.3f}  attempts={report['attempts']}  {report['seconds']}s")
    done = [r for r in rows if not r.get("dry")]
    summary = {"briefs": len(rows), "passed": sum(1 for r in done if r["ok"]), "total_cost_usd": round(sum(r["cost_usd"] for r in done), 4),
               "average_cost_usd": round(sum(r["cost_usd"] for r in done) / len(done), 4) if done else 0, "model": model, "dry": dry}
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "rows": rows}, fh, indent=2)
    return summary


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="premium-golden")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run([x for x in a.only.split(",") if x] or None, a.out, a.model, a.dry), indent=2))
    sys.exit(0)
