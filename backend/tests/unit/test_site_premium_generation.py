"""
tests/unit/test_site_premium_generation.py - SITE-PREMIUM P2: the generation pipeline (mocked Claude) and the guards,
the job and the stale sweep over an in-memory FakeDB (Pattern 3 / 32). No network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import site_premium_generation_service as gen
from app.services import site_premium_prompt as prompt
from app.services.site_ops_service import ValidationFailed
from tests.funnel_fake_db import FakeDB
from tests.unit.premium_gen_fixtures import ART, ARGS, CSS, SKELETON, ScriptedClaude, good_art_reply, good_build_reply
from tests.unit.test_site_premium_render import CONTENT

ORG = "org-1"
BUILDER = "builder-1"


def _art(**over):
    import json
    d = json.loads(json.dumps(ART))
    d.update(over)
    return json.dumps(d)


# ------------------------------------------------------------------ pipeline

class TestPipeline:
    def test_success_on_first_attempts(self):
        c = ScriptedClaude(good_art_reply(), good_build_reply())
        r = gen.design_site(**ARGS, claude=c)
        assert r["ok"] and r["attempts"] == {"art": 1, "build": 1}
        assert (r["usage"].input_tokens, r["usage"].output_tokens, r["usage"].calls) == (2000, 4000, 2)
        assert r["parts"]["tokens"]["--accent"] == "#2F4BFF" and r["art"]["headline_font"] == "Outfit"

    def test_calls_use_the_configured_model_and_limits(self):
        c = ScriptedClaude(good_art_reply(), good_build_reply())
        gen.design_site(**{**ARGS, "model": "claude-test"}, claude=c)
        assert [x["model"] for x in c.calls] == ["claude-test", "claude-test"]
        assert [x["max_tokens"] for x in c.calls] == [gen.ART_MAX_TOKENS, gen.BUILD_MAX_TOKENS]
        assert "Return ONLY a JSON object" in c.calls[0]["system"] and "HTML fragment" in c.calls[1]["system"]

    def test_fenced_replies_are_accepted(self):
        c = ScriptedClaude("```json\n" + good_art_reply() + "\n```", "```html\n" + good_build_reply() + "\n```")
        assert gen.design_site(**ARGS, claude=c)["ok"]

    def test_art_direction_retry_feeds_back_the_reasons(self):
        c = ScriptedClaude(_art(hero_scale="huge"), good_art_reply(), good_build_reply())
        r = gen.design_site(**ARGS, claude=c)
        assert r["ok"] and r["attempts"]["art"] == 2
        assert "hero_scale" in c.calls[1]["user"] and "rejected" in c.calls[1]["user"]

    def test_art_direction_fails_after_one_retry(self):
        c = ScriptedClaude("nope", "still nope")
        r = gen.design_site(**ARGS, claude=c)
        assert not r["ok"] and r["stage"] == "art" and len(c.calls) == 2 and r["usage"].calls == 2

    def test_build_retry_feeds_back_the_reasons_and_the_previous_output(self):
        bad = good_build_reply().replace("var(--font-head)", "'Inter'")
        c = ScriptedClaude(good_art_reply(), bad, good_build_reply())
        r = gen.design_site(**ARGS, claude=c)
        assert r["ok"] and r["attempts"]["build"] == 2
        retry_prompt = c.calls[2]["user"]
        assert "names the font" in retry_prompt and "previous output" in retry_prompt and "Inter" in retry_prompt

    def test_build_fails_after_one_retry_with_the_reasons(self):
        bad = good_build_reply().replace("--ink:#0E1B2C", "--ink:#E0E0E0")   # unreadable on the background
        c = ScriptedClaude(good_art_reply(), bad, bad)
        r = gen.design_site(**ARGS, claude=c)
        assert not r["ok"] and r["stage"] == "build" and any("contrast" in e for e in r["errors"])
        assert len(c.calls) == 3

    def test_a_cut_off_build_is_retried_once_asking_for_a_shorter_page_and_is_still_paid_for(self):
        c = ScriptedClaude(good_art_reply(), gen.OutputTooLong(5000, 20000), good_build_reply())
        r = gen.design_site(**ARGS, claude=c)
        assert r["ok"] and r["attempts"]["build"] == 2
        assert "cut off because it was too long" in c.calls[2]["user"] and "compactly" in c.calls[2]["user"]
        assert r["usage"].output_tokens >= 20000

    def test_two_cut_offs_fail_the_build_without_raising(self):
        c = ScriptedClaude(good_art_reply(), gen.OutputTooLong(5000, 20000), gen.OutputTooLong(5000, 20000))
        r = gen.design_site(**ARGS, claude=c)
        assert not r["ok"] and r["stage"] == "build" and r["usage"].output_tokens >= 40000

    def test_unsafe_markup_is_removed_not_trusted(self):
        evil = good_build_reply().replace("<main>", '<main><script>alert(1)</script><img src=x onerror=alert(1)>')
        r = gen.design_site(**ARGS, claude=ScriptedClaude(good_art_reply(), evil))
        if r["ok"]:
            assert "<script" not in r["parts"]["skeleton_html"] and "onerror" not in r["parts"]["skeleton_html"]
            assert r["parts"]["removed"]
        else:
            assert r["stage"] == "build"

    def test_palette_must_match_the_art_direction(self):
        off = good_build_reply().replace("--accent:#2F4BFF", "--accent:#1F3BEF")
        c = ScriptedClaude(good_art_reply(), off, good_build_reply())
        r = gen.design_site(**ARGS, claude=c)
        assert r["ok"] and r["attempts"]["build"] == 2 and "--accent must be #2F4BFF" in c.calls[2]["user"]

    def test_strict_mode_turns_warnings_into_retries(self):
        no_reduced_motion = good_build_reply().replace("@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}", "")
        c = ScriptedClaude(good_art_reply(), no_reduced_motion, good_build_reply())
        r = gen.design_site(**ARGS, claude=c)
        assert r["ok"] and r["attempts"]["build"] == 2 and "prefers-reduced-motion" in c.calls[2]["user"]

    def test_missing_required_slot_is_fed_back(self):
        no_h1 = good_build_reply().replace('<h1 data-slot="hero.headline"></h1>', "<h1>Static headline</h1>")
        c = ScriptedClaude(good_art_reply(), no_h1, good_build_reply())
        r = gen.design_site(**ARGS, claude=c)
        assert r["ok"] and r["attempts"]["build"] == 2

    def test_a_recent_accent_and_font_combination_is_sent_back_once(self):
        recent = [{"accent_family": "blue", "headline_font": "Outfit"}]
        other = _art(accent_family="green_teal")
        c = ScriptedClaude(good_art_reply(), other, good_build_reply())
        r = gen.design_site(**{**ARGS, "do_not_repeat": recent}, claude=c)
        assert r["attempts"]["art"] == 2 and "used recently" in c.calls[1]["user"]

    def test_a_repeat_on_the_second_try_is_accepted_rather_than_failing(self):
        recent = [{"accent_family": "blue", "headline_font": "Outfit"}]
        c = ScriptedClaude(good_art_reply(), good_art_reply(), good_build_reply())
        assert gen.design_site(**{**ARGS, "do_not_repeat": recent}, claude=c)["ok"]

    def test_section_not_marked_is_a_warning_only(self):
        extra = _art(sections=ART["sections"] + [{"name": "faq", "layout": "faq", "background": "base"}])
        r = gen.design_site(**ARGS, claude=ScriptedClaude(extra, good_build_reply()))
        assert r["ok"] and any("'faq'" in w for w in r["warnings"])

    def test_infrastructure_failure_propagates(self):
        with pytest.raises(gen.GenerationFailed):
            gen.design_site(**ARGS, claude=ScriptedClaude(gen.GenerationFailed("down")))


class TestCost:
    def test_sonnet_rates(self):
        assert gen.cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == 18.0
        assert gen.cost_usd("claude-sonnet-5-5", 2000, 4000) == pytest.approx(0.066)


# ------------------------------------------------------------------ database side

def _site(**over):
    s = {"id": "site-1", "org_id": ORG, "builder_id": BUILDER, "preset_id": "p1", "client_business_name": "Adaeze", "slug": "adaeze-1",
         "status": "preview_ready", "tier": "standard", "current_design_id": None, "deleted_at": None, "content": CONTENT, "brief": {}, "recipe": {"theme": "atelier"}}
    s.update(over)
    return s


def _db(premium=True, **settings):
    return FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "premium_enabled": premium, **settings}],
        sites=[_site()], site_presets=[{"id": "p1", "org_id": ORG, "key": "boutique", "premium_design_notes": "Show the cut."}],
        site_designs=[], site_events=[], site_assets=[])


def _row(db, **over):
    r = {"id": f"d{len(db.rows('site_designs')) + 1}", "org_id": ORG, "site_id": "site-1", "version": len(db.rows("site_designs")) + 1, "kind": "generate",
         "status": "ready", "cost_usd": 0, "created_at": datetime.now(timezone.utc).isoformat(), "art_direction": {}}
    r.update(over)
    db.tables["site_designs"].append(r)
    return r


class TestStartGeneration:
    def test_inserts_a_generating_row(self):
        db = _db()
        row = gen.start_generation(db, ORG, db.rows("sites")[0], "user:u1")
        saved = db.rows("site_designs")[0]
        assert row["id"] == saved["id"] and saved["status"] == "generating" and saved["version"] == 1
        assert saved["model"] == gen.DEFAULT_MODEL and saved["prompt_version"] == prompt.PROMPT_VERSION and saved["created_by"] == "user:u1"

    def test_uses_the_model_from_settings(self):
        db = _db(site_premium_model="claude-other")
        gen.start_generation(db, ORG, db.rows("sites")[0], "u")
        assert db.rows("site_designs")[0]["model"] == "claude-other"

    def test_premium_must_be_switched_on(self):
        db = _db(premium=False)
        with pytest.raises(Exception) as e:
            gen.start_generation(db, ORG, db.rows("sites")[0], "u")
        assert getattr(e.value, "status_code", None) == 403

    def test_needs_content(self):
        db = _db()
        with pytest.raises(ValidationFailed):
            gen.start_generation(db, ORG, _site(content={}), "u")

    def test_one_in_flight_per_site(self):
        db = _db()
        _row(db, status="generating")
        with pytest.raises(gen.AlreadyGenerating):
            gen.start_generation(db, ORG, db.rows("sites")[0], "u")

    def test_a_stale_row_is_swept_so_the_site_is_not_blocked(self):
        db = _db()
        _row(db, status="generating", created_at=(datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat())
        gen.start_generation(db, ORG, db.rows("sites")[0], "u")
        assert [r["status"] for r in db.rows("site_designs")] == ["failed", "generating"]

    def test_per_builder_daily_cap_counts_every_attempt_across_the_builders_sites(self):
        db = _db(site_premium_daily_per_builder=2)
        db.tables["sites"].append(_site(id="site-2"))
        _row(db, site_id="site-2", status="failed")
        _row(db, site_id="site-2", status="ready")
        with pytest.raises(gen.CapReached) as e:
            gen.start_generation(db, ORG, db.rows("sites")[0], "u")
        assert "2 Premium" in str(e.value) and e.value.status_code == 429

    def test_yesterdays_attempts_do_not_count(self):
        db = _db(site_premium_daily_per_builder=1)
        _row(db, created_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
        gen.start_generation(db, ORG, db.rows("sites")[0], "u")

    def test_another_builders_attempts_do_not_count(self):
        db = _db(site_premium_daily_per_builder=1)
        db.tables["sites"].append(_site(id="site-9", builder_id="someone-else"))
        _row(db, site_id="site-9")
        gen.start_generation(db, ORG, db.rows("sites")[0], "u")

    def test_org_cost_cap_pauses_new_designs(self):
        db = _db(site_premium_daily_cost_cap=5)
        db.tables["sites"].append(_site(id="site-9", builder_id="someone-else"))
        _row(db, site_id="site-9", cost_usd=5.2)
        with pytest.raises(gen.CapReached) as e:
            gen.start_generation(db, ORG, db.rows("sites")[0], "u")
        assert "paused" in str(e.value)

    def test_database_race_on_the_unique_index_is_a_409(self):
        db = _db()
        real = db.table

        def table(name):
            q = real(name)
            if name == "site_designs":
                orig = q.execute

                def boom():
                    if q.op == "insert":
                        raise Exception('duplicate key value violates unique constraint "site_designs_one_inflight" (23505)')
                    return orig()
                q.execute = boom
            return q
        db.table = table
        with pytest.raises(gen.AlreadyGenerating):
            gen.start_generation(db, ORG, db.rows("sites")[0], "u")


class TestSweep:
    def test_marks_only_old_in_flight_rows(self):
        db = _db()
        old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        _row(db, id="a", status="generating", created_at=old)
        _row(db, id="b", status="checking", created_at=old)
        _row(db, id="c", status="generating")
        _row(db, id="d", status="ready", created_at=old)
        assert gen.sweep_stale(db) == 2
        assert {r["id"]: r["status"] for r in db.rows("site_designs")} == {"a": "failed", "b": "failed", "c": "generating", "d": "ready"}
        assert db.rows("site_designs")[0]["checks"]["outcome"] == "fallback_standard"


class TestRecentFingerprints:
    def test_only_ready_generated_designs_of_the_same_kind_of_business(self):
        db = _db()
        db.tables["sites"].append(_site(id="site-2", preset_id="other"))
        _row(db, id="x1", art_direction={"concept": "a", "accent_family": "blue", "headline_font": "Outfit", "hero_scale": "mid", "mode": "light", "body_font": "Karla"})
        _row(db, id="x2", site_id="site-2", art_direction={"concept": "b", "accent_family": "red_wine"})
        _row(db, id="x3", status="failed", art_direction={"concept": "c", "accent_family": "violet_pink"})
        out = gen.recent_fingerprints(db, ORG, "p1")
        assert [f["concept"] for f in out] == ["a"]


class TestRunGeneration:
    def _start(self, db):
        return gen.start_generation(db, ORG, db.rows("sites")[0], "user:u1")

    def _run(self, db, claude, render_ok=True):
        row = self._start(db)
        with patch("app.routers.sites._render_and_store", side_effect=(None if render_ok else RuntimeError("boom"))) as render:
            out = gen.run_generation(db, row["id"], claude=claude)
        return row, out, render

    def test_success_saves_the_design_makes_it_current_and_logs_cost(self):
        db = _db()
        row, out, render = self._run(db, ScriptedClaude(good_art_reply(), good_build_reply()))
        d = db.rows("site_designs")[0]
        assert out["ok"] and out["outcome"] == "premium" and out["cost_usd"] == pytest.approx(0.066)
        assert d["status"] == "ready" and d["skeleton_html"] and d["skeleton_css"] and d["slot_manifest"] and d["tokens"]["--accent"] == "#2F4BFF"
        assert d["art_direction"]["fingerprint"]["accent_family"] == "blue"
        assert (d["input_tokens"], d["output_tokens"]) == (2000, 4000) and d["checks"]["outcome"] == "premium" and d["checks"]["visual"] == "not_run_p3"
        site = db.rows("sites")[0]
        assert site["tier"] == "premium" and site["current_design_id"] == row["id"]
        render.assert_called_once()
        assert [e["event"] for e in db.rows("site_events")] == ["premium_design_ready"]

    def test_failure_keeps_the_site_standard_and_records_the_attempt(self):
        db = _db()
        row, out, render = self._run(db, ScriptedClaude("nope", "nope"))
        d = db.rows("site_designs")[0]
        assert not out["ok"] and out["outcome"] == "fallback_standard"
        assert d["status"] == "failed" and d["checks"]["outcome"] == "fallback_standard" and d["checks"]["stage"] == "art"
        site = db.rows("sites")[0]
        assert site["tier"] == "standard" and site["current_design_id"] is None
        render.assert_not_called()
        assert d["cost_usd"] > 0 and [e["event"] for e in db.rows("site_events")] == ["premium_design_failed"]

    def test_a_failed_attempt_leaves_the_previous_design_current(self):
        db = _db()
        db.tables["sites"][0].update(tier="premium", current_design_id="old")
        _, out, _ = self._run(db, ScriptedClaude("x", "y"))
        assert db.rows("sites")[0]["current_design_id"] == "old" and db.rows("sites")[0]["tier"] == "premium"

    def test_service_failure_is_recorded_not_raised(self):
        db = _db()
        _, out, _ = self._run(db, ScriptedClaude(gen.GenerationFailed("The design service could not be reached.")))
        assert out["outcome"] == "fallback_standard" and db.rows("site_designs")[0]["status"] == "failed"

    def test_unexpected_bug_never_leaves_the_row_generating(self):
        db = _db()
        _, out, _ = self._run(db, ScriptedClaude(KeyError("bug")))
        assert out["outcome"] == "fallback_standard" and db.rows("site_designs")[0]["status"] == "failed"

    def test_render_failure_rolls_the_site_back(self):
        db = _db()
        _, out, _ = self._run(db, ScriptedClaude(good_art_reply(), good_build_reply()), render_ok=False)
        site = db.rows("sites")[0]
        assert out["outcome"] == "fallback_standard" and site["tier"] == "standard" and site["current_design_id"] is None
        assert db.rows("site_designs")[0]["status"] == "failed"

    def test_a_redelivered_task_cannot_run_twice(self):
        db = _db()
        row = self._start(db)
        c = ScriptedClaude(good_art_reply(), good_build_reply())
        with patch("app.routers.sites._render_and_store"):
            first = gen.run_generation(db, row["id"], claude=c)
            second = gen.run_generation(db, row["id"], claude=ScriptedClaude())
        assert first["ok"] and second["outcome"] == "not_found"

    def test_a_claimed_row_is_not_picked_up_again(self):
        db = _db()
        row = self._start(db)
        db.tables["site_designs"][0]["status"] = "checking"
        assert gen.run_generation(db, row["id"], claude=ScriptedClaude())["outcome"] == "not_found"

    def test_unknown_design(self):
        assert gen.run_generation(_db(), "missing", claude=ScriptedClaude())["outcome"] == "not_found"

    def test_prompt_gets_the_preset_notes_and_recent_fingerprints(self):
        db = _db()
        _row(db, id="old", site_id="site-1", status="ready", version=0, kind="generate",
             art_direction={"concept": "older", "accent_family": "violet_pink", "headline_font": "Sora", "hero_scale": "mid", "mode": "dark", "body_font": "Manrope"})
        db.tables["site_designs"][0]["created_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        c = ScriptedClaude(good_art_reply(), good_build_reply())
        self._run(db, c)
        assert "Show the cut." in c.calls[0]["user"] and "violet_pink" in c.calls[0]["user"] and "violet_pink" not in c.calls[1]["system"]

    def test_old_versions_are_pruned_to_ten(self):
        db = _db()
        for i in range(12):
            _row(db, id=f"old{i}", version=i + 1, status="ready", created_at=(datetime.now(timezone.utc) - timedelta(days=5)).isoformat())
        self._run(db, ScriptedClaude(good_art_reply(), good_build_reply()))
        assert len(db.rows("site_designs")) == 10


class TestCostCapAlert:
    def test_alerts_managers_once_a_day(self):
        db = _db()
        with patch("app.services.funnel_service._get_manager_ids", return_value=["m1", "m2"]), \
             patch("app.routers.push_notifications.send_push_notification") as push:
            gen.alert_cost_cap(db, ORG, "site-1")
            gen.alert_cost_cap(db, ORG, "site-1")
        assert push.call_count == 2 and len(db.rows("site_events")) == 1

    def test_never_raises(self):
        with patch("app.services.funnel_service._get_manager_ids", side_effect=RuntimeError("x")):
            gen.alert_cost_cap(_db(), ORG, "site-1")


class TestCallClaudeChecked:
    """The real call wrapper, with a fake Anthropic client (no network)."""

    class _Client:
        def __init__(self, result=None, error=None):
            self.calls, self._result, self._error = [], result, error
            self.messages = self

        def create(self, **kw):
            self.calls.append(kw)
            if self._error:
                raise self._error
            return self._result

    @staticmethod
    def _response(text="hi", stop="end_turn", i=11, o=22):
        from types import SimpleNamespace
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                               usage=SimpleNamespace(input_tokens=i, output_tokens=o))

    def _run(self, client):
        with patch("app.services.ai_service._get_client", return_value=client):
            return gen.call_claude_checked("sys", "user", 123, "claude-x")

    def test_returns_text_and_token_counts_and_passes_the_limits(self):
        c = self._Client(self._response("hello", i=5, o=7))
        assert self._run(c) == ("hello", 5, 7)
        kw = c.calls[0]
        assert kw["model"] == "claude-x" and kw["max_tokens"] == 123 and kw["system"] == "sys" and kw["timeout"] == gen.STEP_TIMEOUT_SECONDS
        assert kw["messages"] == [{"role": "user", "content": "user"}]

    def test_a_cut_off_reply_is_a_failure(self):
        with pytest.raises(gen.GenerationFailed) as e:
            self._run(self._Client(self._response(stop="max_tokens")))
        assert "cut off" in str(e.value)

    def test_the_api_reason_is_shown_not_hidden(self):
        import anthropic
        import httpx
        err = anthropic.BadRequestError("Your credit balance is too low to access the Anthropic API.\nPlease go to Plans & Billing.",
                                        response=httpx.Response(400, request=httpx.Request("POST", "http://x")), body=None)
        with pytest.raises(gen.GenerationFailed) as e:
            self._run(self._Client(error=err))
        msg = str(e.value)
        assert "(400)" in msg and "credit balance is too low" in msg and "\n" not in msg

    def test_a_network_error_is_a_failure_not_a_crash(self):
        with pytest.raises(gen.GenerationFailed) as e:
            self._run(self._Client(error=ConnectionError("boom")))
        assert "could not be reached" in str(e.value)

