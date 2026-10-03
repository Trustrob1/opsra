"""
app/services/site_premium_visual.py
------------------------------------
SITE-PREMIUM P1b - the browser (screenshot-time) layout checks of spec section 13A, as one reusable
function. P3 will run the same function in the generation worker; staff can run it today through
backend/premium_visual_check.py.

run_visual_check(html) opens the page in Chromium (Playwright) at 390, 1024 and 1440 px wide and measures
the REAL layout, with the site's own content, so it catches what the static checks cannot:

  errors    horizontal scroll; text running outside the screen; text overlapping other text; text lying
            over a photograph it is not part of (the "headline under the photo" bug); text clipped by a
            container; a photo frame collapsed to nothing; a nav taller than 80 px; a headline under 28 px
            on a phone; a large empty gap between two pieces of text in the same section.
  warnings  button text that wraps; tap targets under 40 px; text under 11 px; photos that failed to
            load; web fonts that did not load (so the measurements used fallback fonts).
  info      how many photo slots are still placeholders.

Playwright is an optional dependency: if it or Chromium is missing, VisualCheckUnavailable is raised and
callers decide what to do (the import script prints how to install it). No network access is needed
beyond what the page itself loads (Google Fonts, the site's photos).
"""
from __future__ import annotations

import os
import re
from typing import Optional

WIDTHS = (390, 1024, 1440)
HEIGHT = {390: 844, 1024: 768, 1440: 900}
NAV_MAX_PX = 80
MAX_TEXT_GAP_PX = 240          # between two pieces of text in one section with no photo between them


class VisualCheckUnavailable(RuntimeError):
    pass


# One script, run in the page for each width. Returns plain findings; Python adds the width.
_MEASURE_JS = r"""
(opts) => {
  const out = {errors: [], warnings: [], info: {}};
  const W = window.innerWidth;
  const de = document.documentElement;
  const vis = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const inClosedDetails = (el) => { const d = el.closest('details'); return d && !d.open && !el.closest('summary'); };
  const fixedish = (el) => { for (let e = el; e && e !== document.body; e = e.parentElement) {
      const p = getComputedStyle(e).position; if (p === 'fixed') return true; } return false; };
  const label = (el) => {
    const t = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    return '<' + el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/)[0] : '') + '> "' + t + '"';
  };
  const rect = (el) => el.getBoundingClientRect();
  const overlapArea = (a, b) => {
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return (w > 0 && h > 0) ? w * h : 0;
  };

  if (de.scrollWidth > W + 1) out.errors.push({check: 'horizontal-scroll', msg: 'The page scrolls sideways (content is ' + de.scrollWidth + 'px wide on a ' + W + 'px screen).'});

  // text leaves: elements that own non-empty direct text
  const leaves = [];
  document.body.querySelectorAll('*').forEach((el) => {
    if (['SCRIPT','STYLE','SVG','PATH','HEAD'].includes(el.tagName.toUpperCase())) return;
    let own = '';
    el.childNodes.forEach((n) => { if (n.nodeType === 3) own += n.textContent; });
    if (!own.trim()) return;
    if (!vis(el) || inClosedDetails(el)) return;
    leaves.push(el);
  });

  // ancestors that clip (overflow hidden/clip/auto/scroll)
  const clippers = (el) => { const r = []; for (let e = el.parentElement; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e); if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') r.push(e); } return r; };

  // 1. text outside the screen, 2. text clipped by a container
  leaves.forEach((el) => {
    if (fixedish(el)) return;
    const r = rect(el);
    const cl = clippers(el);
    if (r.right > W + 2 || r.left < -2) {
      const inside = cl.some((c) => { const cr = rect(c); return cr.right <= W + 2 && cr.left >= -2; });
      if (!inside) out.errors.push({check: 'text-off-screen', msg: label(el) + ' runs outside the screen.'});
    }
    const cs = getComputedStyle(el);
    if (cs.textOverflow === 'ellipsis') return;
    for (const c of cl) {
      const cr = rect(c);
      const cut = Math.max(cr.left - r.left, r.right - cr.right, cr.top - r.top, r.bottom - cr.bottom);
      if (cut > 3 && r.height > 0) { out.errors.push({check: 'text-clipped', msg: label(el) + ' is cut off by its container.'}); break; }
    }
  });

  // 3. text overlapping text
  const sig = leaves.filter((el) => !fixedish(el));
  for (let i = 0; i < sig.length; i++) {
    for (let j = i + 1; j < sig.length; j++) {
      const a = sig[i], b = sig[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ra = rect(a), rb = rect(b);
      const area = overlapArea(ra, rb);
      if (!area) continue;
      const smaller = Math.min(ra.width * ra.height, rb.width * rb.height);
      if (area / smaller > 0.25) out.errors.push({check: 'text-overlap', msg: label(a) + ' overlaps ' + label(b) + '.'});
    }
  }

  // 4. text lying over a photo it is not part of
  const media = [...document.querySelectorAll('img, .slot-ph, svg')].filter((m) => vis(m) && !fixedish(m) && !m.closest('button, a'));
  leaves.forEach((el) => {
    if (fixedish(el) || el.closest('svg')) return;
    const re = rect(el);
    media.forEach((m) => {
      if (m.contains(el)) return;
      const host = m.closest('figure') || m.parentElement;
      if (host && host.contains(el)) return;            // a caption or overlay that belongs to the photo
      const rm = rect(m);
      if (rm.width < 80 || rm.height < 80) return;       // icons
      const area = overlapArea(re, rm);
      if (area / (re.width * re.height) > 0.1) out.errors.push({check: 'text-over-photo', msg: label(el) + ' lies over a photograph.'});
    });
  });

  // 5. photo frames that collapsed, broken images, placeholders
  let placeholders = 0;
  document.querySelectorAll('img, .slot-ph').forEach((m) => {
    if (inClosedDetails(m)) return;
    if (!m.getClientRects().length) return;           // hidden by a parent (for example a phone-only layout)
    const cs = getComputedStyle(m);
    if (cs.display === 'none') return;
    const r = rect(m);
    if (m.classList.contains('slot-ph')) placeholders++;
    if ((r.height < 20 || r.width < 20) && (m.closest('figure') || m.classList.contains('slot-ph'))) out.errors.push({check: 'empty-photo-frame', msg: 'A photo frame is ' + Math.round(r.width) + ' by ' + Math.round(r.height) + 'px: it has collapsed.'});
    if (m.tagName === 'IMG' && m.complete && m.naturalWidth === 0) out.warnings.push({check: 'photo-failed', msg: 'A photo failed to load: ' + (m.getAttribute('src') || '').slice(0, 80)});
  });
  out.info.placeholders = placeholders;

  // 6. nav height
  const nav = document.querySelector('[data-section="nav"], header, nav');
  if (nav && vis(nav) && rect(nav).height > opts.navMax) out.errors.push({check: 'nav-too-tall', msg: 'The navigation bar is ' + Math.round(rect(nav).height) + 'px tall; the limit is ' + opts.navMax + 'px.'});

  // 7. headline size on phones
  const h1 = document.querySelector('h1');
  if (h1 && vis(h1) && W <= 480 && parseFloat(getComputedStyle(h1).fontSize) < 28) out.errors.push({check: 'headline-too-small', msg: 'The main headline is under 28px on a phone.'});

  // 8. empty gaps between text in one section
  document.querySelectorAll('[data-section], main > section').forEach((sec) => {
    if (sec.matches('[data-section="nav"], [data-section="footer"]')) return;
    const items = leaves.filter((el) => sec.contains(el) && !fixedish(el)).map((el) => ({el, r: rect(el)})).sort((a, b) => a.r.top - b.r.top);
    for (let i = 0; i < items.length - 1; i++) {
      const a = items[i], b = items[i + 1];
      if (b.r.top - a.r.bottom <= opts.gapMax) continue;
      const xo = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
      if (xo <= 0) continue;                              // different columns
      const between = media.some((m) => { const rm = rect(m); return rm.top < b.r.top && rm.bottom > a.r.bottom && Math.min(rm.right, b.r.right) - Math.max(rm.left, a.r.left) > 0; });
      if (between) continue;
      out.errors.push({check: 'empty-gap', msg: 'There is a ' + Math.round(b.r.top - a.r.bottom) + 'px empty gap between ' + label(a.el) + ' and ' + label(b.el) + '.'});
    }
  });

  // 9. warnings: wrapped buttons, small tap targets, tiny text
  document.querySelectorAll('a').forEach((a) => {
    if (!vis(a) || inClosedDetails(a)) return;
    const cs = getComputedStyle(a);
    const padded = parseFloat(cs.paddingLeft) >= 8 && parseFloat(cs.paddingRight) >= 8;
    const range = document.createRange(); range.selectNodeContents(a);
    const lines = new Set([...range.getClientRects()].map((q) => Math.round(q.top))).size;
    if (padded && lines > 1) out.warnings.push({check: 'button-wraps', msg: 'The button text wraps onto ' + lines + ' lines: ' + label(a)});
    const r = rect(a);
    if (W <= 480 && r.height > 0 && r.height < 40 && (a.className || '').toString().match(/btn|button|cta|fab/)) out.warnings.push({check: 'small-tap-target', msg: 'The button is only ' + Math.round(r.height) + 'px tall: ' + label(a)});
  });
  leaves.forEach((el) => { if (parseFloat(getComputedStyle(el).fontSize) < 11) out.warnings.push({check: 'tiny-text', msg: 'Text under 11px: ' + label(el)}); });

  out.info.fonts = [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/['"]/g, ''));
  return out;
}
"""


def _dedupe(items: list) -> list:
    seen, out = set(), []
    for it in items:
        key = (it["check"], it["msg"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def run_visual_check(html: str, *, widths=WIDTHS, screenshot_dir: Optional[str] = None, extra_css: str = "",
                     font_timeout_ms: int = 8000, label: str = "page") -> dict:
    """Measure `html` in Chromium. Returns
    {"ok": bool, "errors": [{check, width, msg}], "warnings": [...], "info": {...}, "screenshots": [paths]}."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise VisualCheckUnavailable("Playwright is not installed (pip install playwright, then: playwright install chromium)") from exc

    errors: list = []
    warnings: list = []
    info: dict = {"placeholders": 0, "fonts_loaded": []}
    shots: list = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for w in widths:
                    page = browser.new_page(viewport={"width": w, "height": HEIGHT.get(w, 800)}, reduced_motion="reduce")
                    page.set_content(html, wait_until="load")
                    if extra_css:
                        page.add_style_tag(content=extra_css)
                    try:
                        page.evaluate("document.fonts.ready")
                        page.wait_for_function("document.fonts.status === 'loaded'", timeout=font_timeout_ms)
                    except Exception:
                        pass
                    page.wait_for_timeout(300)
                    res = page.evaluate(_MEASURE_JS, {"navMax": NAV_MAX_PX, "gapMax": MAX_TEXT_GAP_PX})
                    for e in res["errors"]:
                        errors.append({**e, "width": w})
                    for e in res["warnings"]:
                        warnings.append({**e, "width": w})
                    info["placeholders"] = max(info["placeholders"], res["info"].get("placeholders", 0))
                    info["fonts_loaded"] = sorted(set(info["fonts_loaded"]) | set(res["info"].get("fonts", [])))
                    if screenshot_dir:
                        os.makedirs(screenshot_dir, exist_ok=True)
                        path = os.path.join(screenshot_dir, f"{label}-{w}.png")
                        page.screenshot(path=path, full_page=True)
                        shots.append(path)
                    page.close()
            finally:
                browser.close()
    except VisualCheckUnavailable:
        raise
    except Exception as exc:
        msg = str(exc)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            raise VisualCheckUnavailable("Chromium is not installed for Playwright (run: playwright install chromium)") from exc
        raise

    if not info["fonts_loaded"]:
        warnings.append({"check": "fonts-not-loaded", "width": 0,
                         "msg": "No web fonts loaded, so the layout was measured with fallback fonts. Check the internet connection and run again."})
    return {"ok": not errors, "errors": _dedupe(errors), "warnings": _dedupe(warnings), "info": info, "screenshots": shots}


def summarise(report: dict) -> str:
    """A short plain-text report for the console."""
    lines = ["VISUAL CHECK: " + ("PASSED" if report["ok"] else "FAILED") +
             f" ({len(report['errors'])} errors, {len(report['warnings'])} warnings, "
             f"{report['info'].get('placeholders', 0)} photo placeholders)"]
    for e in report["errors"]:
        lines.append(f"  ERROR   [{e['width']}px] {e['check']}: {e['msg']}")
    for e in report["warnings"]:
        lines.append(f"  warning [{e['width']}px] {e['check']}: {e['msg']}")
    for s in report.get("screenshots", []):
        lines.append("  screenshot: " + s)
    return "\n".join(lines)
