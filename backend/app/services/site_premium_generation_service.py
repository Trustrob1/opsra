"""
app/services/site_premium_generation_service.py
-------------------------------------------------
SITE-PREMIUM P2 - Claude designs a Premium site (spec sections 4, 8, 12).

Two halves, so the web request stays fast and the slow part runs in a Celery worker:
  start_generation()  - guards (Premium on, content present, per-builder and org cost caps, one in flight per
                        site) and inserts a site_designs row with status 'generating'. Cheap, runs in the request.
  run_generation()    - the pipeline, run by the worker: art direction -> build -> sanitise + strict static checks
                        (one retry with the reasons fed back) -> trial render -> save. Never raises.

Rules:
  * Pass means the design becomes the site's current design and the preview is re-rendered.
    Fail means the site stays exactly as it was (Standard) and the failed attempt is kept for the cost log.
  * Every call logs tokens and cost on the design row and in claude_usage_log (spec section 12).
  * The model is told nothing it could abuse: it has no tools and fetches nothing. Client text is data.
  * Screenshot checks and the critique pass arrive in P3. Static checks only here.
  * The charge/credit for a failed attempt belongs to P5 (checkout). A failed attempt never uses a redesign.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from app.services import site_premium_fonts as fonts
from app.services import site_premium_prompt as prompt
from app.services import site_premium_renderer as renderer
from app.services import site_premium_service as premium
from app.services.site_ops_service import NotFound, SiteOpsError, ValidationFailed
from app.services.site_premium_prompt import ArtDirectionError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5"
ART_MAX_TOKENS = 2_000
BUILD_MAX_TOKENS = 20_000   # p2.2 pages run 12k to 17k tokens; 16k cut off a golden-set brief
STEP_TIMEOUT_SECONDS = 240
STALE_AFTER_MINUTES = 20
RECENT_FOR_REPEAT = 12
LAGOS = ZoneInfo("Africa/Lagos")

ClaudeFn = Callable[[str, str, int, str], tuple[str, int, int]]   # (system, user, max_tokens, model) -> (text, in, out)


class CapReached(SiteOpsError):
    status_code = 429
    code = "RATE_LIMITED"


class AlreadyGenerating(SiteOpsError):
    status_code = 409
    code = "CONFLICT"


# ------------------------------------------------------------------ small helpers

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _today_start_iso() -> str:
    """Midnight in Lagos, as UTC: the 'per day' of the caps follows the owner's day."""
    local = _now().astimezone(LAGOS).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).isoformat()


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    from app.services.ai_service import _get_cost_rate
    rates = _get_cost_rate(model)
    return round(input_tokens / 1_000_000 * rates["input"] + output_tokens / 1_000_000 * rates["output"], 6)


def _is_duplicate(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "23505" in text or "duplicate" in text or "unique" in text


# ------------------------------------------------------------------ the Claude call

def call_claude_checked(system: str, user: str, max_tokens: int, model: str) -> tuple[str, int, int]:
    """One Claude call that RAISES on failure (ai_service.call_claude swallows errors, which would hide a failed design)
    and returns the token counts. Same client, same retry rule (rate limit and 5xx, three tries)."""
    import anthropic
    from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
    from app.services import ai_service

    client = ai_service._get_client()

    @retry(retry=retry_if_exception(ai_service._is_retryable), wait=wait_exponential(multiplier=1, min=2, max=20),
           stop=stop_after_attempt(3), reraise=True)
    def _go():
        return client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                      messages=[{"role": "user", "content": user}], timeout=STEP_TIMEOUT_SECONDS)

    try:
        response = _go()
    except anthropic.APIStatusError as exc:
        detail = " ".join(str(getattr(exc, "message", "") or exc).split())[:240]   # Anthropic's own reason (no secrets in it)
        logger.warning("site_premium_generation: Claude API error %s: %s", exc.status_code, detail)
        reason = service_problem(exc.status_code, detail)
        if reason == "no_credit":
            raise GenerationFailed("The design service has run out of credit, so no design was made and nothing was used up. "
                                   "Add credit to the Anthropic account and try again.", reason=reason)
        if reason == "bad_key":
            raise GenerationFailed("The design service rejected its access key, so no design was made and nothing was used up. "
                                   "The Anthropic API key needs to be checked.", reason=reason)
        raise GenerationFailed(f"The design service returned an error ({exc.status_code}): {detail}")
    except Exception as exc:  # S14
        logger.warning("site_premium_generation: Claude call failed: %s: %s", type(exc).__name__, exc)
        raise GenerationFailed(f"The design service could not be reached ({type(exc).__name__}).")
    text = "".join(b.text for b in (response.content or []) if getattr(b, "type", None) == "text")
    usage = getattr(response, "usage", None)
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise OutputTooLong(int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0))
    return text, int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)


def service_problem(status_code: int, detail: str) -> Optional[str]:
    """'no_credit' or 'bad_key' when the Anthropic account itself is the problem (nothing the design or the
    customer can fix), else None. Anthropic answers an empty balance with a 400 whose text names the credit balance."""
    text = (detail or "").lower()
    if status_code == 402 or "credit balance" in text or "purchase credits" in text:
        return "no_credit"
    if status_code in (401, 403):
        return "bad_key"
    return None


class GenerationFailed(Exception):
    """A step failed in a way that is not the model's fault to fix (network, cut-off, no reply).
    `reason` is 'no_credit' or 'bad_key' when the Anthropic account is the cause."""

    def __init__(self, message: str = "", reason: Optional[str] = None):
        super().__init__(message)
        self.reason = reason


class OutputTooLong(GenerationFailed):
    """The reply hit the token cap. It carries the tokens already spent so the cost is still recorded, and the build
    step retries once asking for a much shorter page."""

    def __init__(self, input_tokens: int = 0, output_tokens: int = 0):
        super().__init__("The design was cut off because it was too long.")
        self.input_tokens, self.output_tokens = input_tokens, output_tokens


TOO_LONG_NOTE = ("Your previous output was cut off because it was too long. Write the whole page again, much more compactly: "
                 "at most 36 KB of HTML plus CSS together. Group selectors, use custom properties and clamp(), no repeated "
                 "declarations, no comments, short class names, one compact rule per component.")


# ------------------------------------------------------------------ guards (run in the request)

def settings_for(db: Any, org_id: str) -> dict:
    return _one((db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data) or {}


def sweep_stale(db: Any, org_id: Optional[str] = None, site_id: Optional[str] = None) -> int:
    """A worker that died leaves a row 'generating' forever, which would block the site (one in flight).
    Anything older than STALE_AFTER_MINUTES is marked failed. Returns how many were swept."""
    cutoff = (_now() - timedelta(minutes=STALE_AFTER_MINUTES)).isoformat()
    q = db.table("site_designs").select("id, org_id, site_id, status, created_at").in_("status", ["generating", "checking"]).lt("created_at", cutoff)
    if org_id:
        q = q.eq("org_id", org_id)
    if site_id:
        q = q.eq("site_id", site_id)
    rows = q.execute().data or []
    swept = 0
    for r in rows:
        try:
            res = (db.table("site_designs").update({"status": "failed", "checks": {"outcome": "fallback_standard", "errors": ["The design took too long and was stopped."]}})
                   .eq("id", r["id"]).eq("org_id", r["org_id"]).in_("status", ["generating", "checking"]).execute())
            swept += len(res.data or [])
        except Exception as exc:  # S14
            logger.warning("site_premium_generation: sweep failed design=%s: %s", r.get("id"), exc)
    return swept


def check_caps(db: Any, org_id: str, site: dict, settings: dict) -> None:
    """Spec section 8: at most N generations per builder per day, and an org daily cost cap."""
    since = _today_start_iso()
    per_builder = int(settings.get("site_premium_daily_per_builder") or 3)
    builder_id = site.get("builder_id")
    if builder_id:
        site_ids = [r["id"] for r in (db.table("sites").select("id").eq("org_id", org_id).eq("builder_id", builder_id).execute().data or [])]
    else:
        site_ids = [site["id"]]
    if site_ids:
        tried = (db.table("site_designs").select("id, status, checks, cost_usd").eq("org_id", org_id).in_("site_id", site_ids)
                 .in_("kind", ["generate", "redesign"]).gte("created_at", since).execute().data or [])
        # an attempt that failed because the design service itself was down or out of credit used nothing: not counted
        tried = [r for r in tried if not (r.get("status") == "failed" and (r.get("checks") or {}).get("stage") == "service"
                                          and not float(r.get("cost_usd") or 0))]
        if len(tried) >= per_builder:
            raise CapReached(f"You can design {per_builder} Premium sites a day. Please try again tomorrow.")
    cap = float(settings.get("site_premium_daily_cost_cap") or 20)
    spent = sum(float(r.get("cost_usd") or 0) for r in
                (db.table("site_designs").select("cost_usd").eq("org_id", org_id).gte("created_at", since).execute().data or []))
    if spent >= cap:
        raise CapReached("Premium design is paused for today. Please try again tomorrow.")


def start_generation(db: Any, org_id: str, site: dict, actor: str) -> dict:
    """Guards, then insert the 'generating' row. The Celery task is queued by the caller with the returned id."""
    settings = settings_for(db, org_id)
    premium.require_enabled(settings)
    if not (site.get("content") or {}):
        raise ValidationFailed("This site has no content yet. Build the Standard preview first.")
    sweep_stale(db, org_id, site["id"])
    inflight = (db.table("site_designs").select("id").eq("site_id", site["id"]).eq("org_id", org_id)
                .in_("status", ["generating", "checking"]).limit(1).execute()).data
    if inflight:
        raise AlreadyGenerating("A design is already being made for this site. It will be ready in a few minutes.")
    check_caps(db, org_id, site, settings)
    existing = (db.table("site_designs").select("id, version").eq("site_id", site["id"]).eq("org_id", org_id).execute()).data or []
    version = max((int(r["version"]) for r in existing), default=0) + 1
    row = {
        "org_id": org_id, "site_id": site["id"], "version": version, "kind": "generate",
        "parent_id": site.get("current_design_id"), "skeleton_html": "", "skeleton_css": "",
        "slot_manifest": {}, "art_direction": {}, "tokens": {}, "model": settings.get("site_premium_model") or DEFAULT_MODEL,
        "prompt_version": prompt.PROMPT_VERSION, "status": "generating", "staged": False, "checks": {},
        "created_by": actor, "created_at": _now_iso(),
    }
    try:
        inserted = _one((db.table("site_designs").insert(row).execute()).data) or {}
    except Exception as exc:
        if _is_duplicate(exc):   # the database's one-in-flight index caught a race
            raise AlreadyGenerating("A design is already being made for this site. It will be ready in a few minutes.")
        raise
    if not inserted.get("id"):
        raise SiteOpsError("The design could not be started. Nothing was changed.")
    return inserted


def alert_service_problem(db: Any, org_id: str, site_id: str, reason: str) -> None:
    """Tell managers once a day that the AI account is out of credit (or its key was refused). S14: never raises."""
    try:
        event = "premium_no_credit" if reason == "no_credit" else "premium_bad_key"
        done = (db.table("site_events").select("id").eq("org_id", org_id).eq("event", event).gte("created_at", _today_start_iso()).limit(1).execute()).data
        if done:
            return
        db.table("site_events").insert({"org_id": org_id, "site_id": site_id, "order_id": None, "actor": "system",
                                        "event": event, "detail": {}, "created_at": _now_iso()}).execute()
        from app.services.funnel_service import _get_manager_ids
        from app.routers.push_notifications import send_push_notification
        title = "Premium designs stopped: AI credit is empty" if reason == "no_credit" else "Premium designs stopped: AI key refused"
        body = ("Add credit to the Anthropic account. Premium designs resume as soon as it is topped up." if reason == "no_credit"
                else "The Anthropic API key was refused. Check the key in the server settings.")
        for uid in _get_manager_ids(db, org_id):
            send_push_notification(db=db, user_id=uid, title=title, body=body)
    except Exception as exc:  # S14
        logger.warning("site_premium_generation: service alert failed org=%s: %s", org_id, exc)


def alert_cost_cap(db: Any, org_id: str, site_id: str) -> None:
    """Tell managers once a day that the cost cap stopped new designs. S14: never raises."""
    try:
        since = _today_start_iso()
        done = (db.table("site_events").select("id").eq("org_id", org_id).eq("event", "premium_cost_cap_hit").gte("created_at", since).limit(1).execute()).data
        if done:
            return
        db.table("site_events").insert({"org_id": org_id, "site_id": site_id, "order_id": None, "actor": "system",
                                        "event": "premium_cost_cap_hit", "detail": {}, "created_at": _now_iso()}).execute()
        from app.services.funnel_service import _get_manager_ids
        from app.routers.push_notifications import send_push_notification
        for uid in _get_manager_ids(db, org_id):
            send_push_notification(db=db, user_id=uid, title="Premium designs paused",
                                   body="The daily Premium design cost limit was reached. New designs resume tomorrow.")
    except Exception as exc:  # S14
        logger.warning("site_premium_generation: cost cap alert failed org=%s: %s", org_id, exc)


# ------------------------------------------------------------------ inputs

def recent_fingerprints(db: Any, org_id: str, preset_id: Optional[str], limit: int = RECENT_FOR_REPEAT) -> list[dict]:
    """The anti-sameness list: art-direction fingerprints of the latest designs for this kind of business in this org."""
    q = db.table("sites").select("id").eq("org_id", org_id)
    if preset_id:
        q = q.eq("preset_id", preset_id)
    ids = [r["id"] for r in (q.limit(200).execute().data or [])]
    if not ids:
        return []
    rows = (db.table("site_designs").select("art_direction, created_at").eq("org_id", org_id).in_("site_id", ids)
            .eq("status", "ready").in_("kind", ["generate", "redesign"]).order("created_at", desc=True).limit(limit).execute().data or [])
    return [prompt.fingerprint(r["art_direction"]) for r in rows if r.get("art_direction")]


class Usage:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def add(self, i: int, o: int) -> None:
        self.input_tokens += i
        self.output_tokens += o
        self.calls += 1


# ------------------------------------------------------------------ the pipeline (pure: no database)

def _palette_errors(css: str, art: dict) -> list[str]:
    from app.services.site_premium_checks import root_hex_vars
    tokens = root_hex_vars(css)
    out = []
    for var, key in (("--accent", "accent_hex"), ("--bg", "bg_hex"), ("--ink", "ink_hex")):
        have = (tokens.get(var) or "").upper()
        if have != art[key]:
            out.append(f"{var} must be {art[key]} as set in the art direction (found {have or 'nothing'}).")
    return out


def _missing_sections(html: str, art: dict) -> list[str]:
    names = set()
    stack = list(renderer.parse_fragment(html))
    while stack:
        n = stack.pop()
        if getattr(n, "tag", None):
            if n.attrs.get("data-section"):
                names.add(n.attrs["data-section"])
            stack.extend(n.children)
    return [s["name"] for s in art["sections"] if s["name"] not in names and s["name"] not in ("nav", "footer")]


def design_site(*, content: dict, brief: Any, niche: Optional[str], personality: Optional[str], assets: list[dict],
                assets_by_id: dict, design_notes: str, do_not_repeat: list[dict], model: str,
                claude: ClaudeFn = call_claude_checked) -> dict:
    """Run the whole design pipeline. Returns:
       {"ok": True, "art": {...}, "parts": {...validate_skeleton result...}, "usage": Usage, "attempts": {...}, "warnings": [...]}
       or {"ok": False, "stage": "art"|"build", "errors": [...], "usage": Usage, "attempts": {...}}.
    Raises GenerationFailed only for infrastructure failures (no reply, cut off, unreachable)."""
    usage = Usage()
    attempts = {"art": 0, "build": 0}

    # 1. art direction (one retry with the reasons)
    art: Optional[dict] = None
    errors: list[str] = []
    base_user = prompt.build_art_user(business_name=(content.get("business") or {}).get("name", ""), niche=niche,
                                      personality=personality, brief=brief, content=content, assets=assets,
                                      design_notes=design_notes, do_not_repeat=do_not_repeat)
    for attempt in (1, 2):
        attempts["art"] = attempt
        user = base_user if not errors else base_user + "\n\nYour previous answer was rejected:\n" + "\n".join(f"- {e}" for e in errors) + "\nReturn the corrected JSON."
        text, i, o = claude(prompt.ART_SYSTEM, user, ART_MAX_TOKENS, model)
        usage.add(i, o)
        try:
            art = prompt.parse_art_direction(text, niche)
            repeats = [f for f in do_not_repeat if f.get("accent_family") == art["accent_family"] and f.get("headline_font") == art["headline_font"]]
            if repeats and attempt == 1:
                errors = [f"The accent family {art['accent_family']} with {art['headline_font']} was used recently for this kind of business. Choose a different accent family or headline font."]
                art = None
                continue
            break
        except ArtDirectionError as exc:
            errors, art = exc.errors, None
    if art is None:
        return {"ok": False, "stage": "art", "errors": errors, "usage": usage, "attempts": attempts}

    # 2. build + sanitise + strict static checks (one retry)
    errors, previous = [], None
    head, body = art["headline_font"], art["body_font"]
    for attempt in (1, 2):
        attempts["build"] = attempt
        user = prompt.build_design_user(art=art, content=content, assets=assets, design_notes=design_notes,
                                        errors=errors or None, previous=previous)
        try:
            text, i, o = claude(prompt.BUILD_SYSTEM, user, BUILD_MAX_TOKENS, model)
        except OutputTooLong as exc:   # cut off: pay for it in the totals, then ask once for a much shorter page
            usage.add(exc.input_tokens, exc.output_tokens)
            errors, previous = [TOO_LONG_NOTE], None
            continue
        usage.add(i, o)
        try:
            raw = prompt.extract_skeleton(text)
            previous = raw
            parts = premium.validate_skeleton(raw, content, head, body, assets_by_id, strict=True)
            palette = _palette_errors(parts["skeleton_css"], art)
            if palette:
                raise ValidationFailed("Skeleton not accepted: " + "; ".join(palette))
            warnings = [f"The art direction lists a section '{n}' that the page does not mark with data-section." for n in _missing_sections(parts["skeleton_html"], art)]
            return {"ok": True, "art": art, "parts": parts, "usage": usage, "attempts": attempts, "warnings": warnings}
        except ArtDirectionError as exc:
            errors = exc.errors
        except ValidationFailed as exc:
            errors = list(getattr(exc, "errors", None) or [str(exc)])
            if not hasattr(exc, "errors") and "Skeleton not accepted: " in str(exc):
                errors = str(exc).split("Skeleton not accepted: ", 1)[1].split("; ")
    return {"ok": False, "stage": "build", "errors": errors, "usage": usage, "attempts": attempts}


# ------------------------------------------------------------------ the job (database around the pipeline)

def _log_event(db: Any, org_id: str, site_id: str, actor: str, event: str, detail: Optional[dict] = None) -> None:
    try:
        db.table("site_events").insert({"org_id": org_id, "site_id": site_id, "order_id": None, "actor": actor,
                                        "event": event, "detail": detail or {}, "created_at": _now_iso()}).execute()
    except Exception as exc:  # S14
        logger.warning("site_premium_generation: event insert failed %s: %s", event, exc)


def _log_usage(db: Any, org_id: str, model: str, usage: Usage) -> None:
    try:
        from app.services.ai_service import _log_claude_usage
        _log_claude_usage(db, org_id=org_id, function_name="site_premium_generate", model=model,
                          input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
    except Exception as exc:  # S14
        logger.warning("site_premium_generation: usage log failed: %s", exc)


def _finish_failed(db: Any, design: dict, usage: Usage, started: float, model: str, checks: dict) -> dict:
    spent = cost_usd(model, usage.input_tokens, usage.output_tokens)
    checks = {**checks, "outcome": "fallback_standard"}
    db.table("site_designs").update({
        "status": "failed", "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "cost_usd": spent,
        "duration_ms": int((time.monotonic() - started) * 1000), "checks": checks,
    }).eq("id", design["id"]).eq("org_id", design["org_id"]).execute()
    _log_usage(db, design["org_id"], model, usage)
    _log_event(db, design["org_id"], design["site_id"], "system", "premium_design_failed",
               {"design_id": design["id"], "stage": checks.get("stage"), "cost_usd": spent, "errors": (checks.get("errors") or [])[:5]})
    return {"ok": False, "design_id": design["id"], "outcome": "fallback_standard", "cost_usd": spent, "errors": checks.get("errors", [])}


def run_generation(db: Any, design_id: str, claude: ClaudeFn = call_claude_checked) -> dict:
    """The worker job. Never raises: a problem is recorded on the design row and the site stays Standard."""
    started = time.monotonic()
    design = _one((db.table("site_designs").select("*").eq("id", design_id).eq("status", "generating").limit(1).execute()).data)
    if not design:
        return {"ok": False, "design_id": design_id, "outcome": "not_found"}
    # Claim the row. The queue delivers late-acknowledged tasks again if a worker dies, so a second run must find it taken.
    claimed = (db.table("site_designs").update({"status": "checking"}).eq("id", design_id).eq("org_id", design["org_id"])
               .eq("status", "generating").execute()).data
    if not claimed:
        return {"ok": False, "design_id": design_id, "outcome": "already_running"}
    org_id, site_id = design["org_id"], design["site_id"]
    usage = Usage()
    model = design.get("model") or DEFAULT_MODEL
    try:
        site = _one((db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).is_("deleted_at", "null").limit(1).execute()).data)
        if not site or not (site.get("content") or {}):
            return _finish_failed(db, design, usage, started, model, {"stage": "inputs", "errors": ["The site has no content to design from."]})
        preset = _one((db.table("site_presets").select("*").eq("id", site["preset_id"]).eq("org_id", org_id).limit(1).execute()).data) if site.get("preset_id") else None
        assets = (db.table("site_assets").select("id, slot, public_url, width, height").eq("site_id", site_id).execute()).data or []
        assets_by_id = {a["id"]: {"public_url": a["public_url"], "width": a.get("width"), "height": a.get("height")} for a in assets}
        niche = (preset or {}).get("key")
        result = design_site(
            content=site["content"], brief=site.get("brief") or {}, niche=niche, personality=(site.get("brief") or {}).get("personality") if isinstance(site.get("brief"), dict) else None,
            assets=assets, assets_by_id=assets_by_id, design_notes=(preset or {}).get("premium_design_notes") or "",
            do_not_repeat=recent_fingerprints(db, org_id, site.get("preset_id")), model=model, claude=claude)
    except GenerationFailed as exc:
        if exc.reason:
            alert_service_problem(db, design["org_id"], design["site_id"], exc.reason)
        return _finish_failed(db, design, usage, started, model, {"stage": "service", "errors": [str(exc)], "reason": exc.reason})
    except Exception as exc:  # S14 - a bug must never leave the row 'generating'
        logger.exception("site_premium_generation: unexpected failure design=%s", design_id)
        return _finish_failed(db, design, usage, started, model, {"stage": "unexpected", "errors": [f"Unexpected problem ({type(exc).__name__})."]})

    usage = result["usage"]
    if not result["ok"]:
        return _finish_failed(db, design, usage, started, model, {"stage": result["stage"], "errors": result["errors"], "attempts": result["attempts"]})

    parts, art = result["parts"], result["art"]
    spent = cost_usd(model, usage.input_tokens, usage.output_tokens)
    update = {
        "skeleton_html": parts["skeleton_html"], "skeleton_css": parts["skeleton_css"], "slot_manifest": parts["slot_manifest"],
        "art_direction": {**art, "fingerprint": prompt.fingerprint(art)}, "tokens": parts["tokens"],
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "cost_usd": spent,
        "duration_ms": int((time.monotonic() - started) * 1000), "status": "ready",
        "checks": {"sanitiser": "ok", "contract": "ok", "slots": "ok", "static": {"errors": [], "warnings": result["warnings"] + parts["static_warnings"]},
                   "removed": parts["removed"], "attempts": result["attempts"], "visual": "not_run_p3", "outcome": "premium"},
    }
    prev_tier, prev_design = site.get("tier") or "standard", site.get("current_design_id")
    ok = (db.table("site_designs").update(update).eq("id", design_id).eq("org_id", org_id).eq("status", "checking").execute()).data
    if not ok:
        return {"ok": False, "design_id": design_id, "outcome": "superseded"}
    try:   # make it current and re-render; a render failure rolls the site back to what it was
        db.table("sites").update({"tier": "premium", "current_design_id": design_id, "updated_at": _now_iso()}).eq("id", site_id).eq("org_id", org_id).execute()
        from app.routers.sites import _render_and_store
        site["tier"], site["current_design_id"] = "premium", design_id
        _render_and_store(db, org_id, site)
    except Exception as exc:  # S14
        logger.warning("site_premium_generation: render after generation failed site=%s: %s", site_id, exc)
        db.table("sites").update({"tier": prev_tier, "current_design_id": prev_design}).eq("id", site_id).eq("org_id", org_id).execute()
        db.table("site_designs").update({"status": "failed", "checks": {**update["checks"], "stage": "render", "errors": ["The finished design could not be shown."], "outcome": "fallback_standard"}}).eq("id", design_id).execute()
        _log_usage(db, org_id, model, usage)
        return {"ok": False, "design_id": design_id, "outcome": "fallback_standard", "cost_usd": spent, "errors": ["render"]}
    premium._prune(db, org_id, site_id, keep_id=design_id)
    _log_usage(db, org_id, model, usage)
    _log_event(db, org_id, site_id, "system", "premium_design_ready",
               {"design_id": design_id, "version": design["version"], "cost_usd": spent, "attempts": result["attempts"],
                "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})
    return {"ok": True, "design_id": design_id, "outcome": "premium", "cost_usd": spent, "version": design["version"]}
