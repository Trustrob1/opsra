"""SITE-PREMIUM P4-4: design history, restore and 'Try another design' (held-back redesign). In-memory FakeDB, mocked Claude."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import site_premium_generation_service as gen
from app.services import site_premium_history as hist
from app.services.site_ops_service import Conflict, NotFound, ValidationFailed
from tests.unit.premium_gen_fixtures import ScriptedClaude, good_art_reply, good_build_reply
from tests.unit.test_site_premium_generation import ORG, _db, _row, _site

NOW = datetime.now(timezone.utc)


def premium_db(**settings):
    """A Premium site whose current design is d1 (a first design)."""
    db = _db(**settings)
    db.tables["sites"][0].update(tier="premium", current_design_id="d1")
    _row(db, id="d1", version=1, kind="generate", art_direction={"fingerprint": {"accent_family": "blue"}, "accent_family": "blue"})
    return db


def site(db):
    return db.rows("sites")[0]


class TestLabels:
    @pytest.mark.parametrize("kind,checks,label", [
        ("generate", {}, "First design"),
        ("redesign", {}, "New design"),
        ("import", {}, "Imported design"),
        ("patch", {"tweak": {"changes": {"accent": "#C0243B"}}}, "Brand colour changed"),
        ("patch", {"tweak": {"changes": {"accent": "#C0243B", "headline_font": "Lora"}}}, "Brand colour, fonts changed"),
        ("patch", {"tweak": {"changes": {"sections": {"about": "dark"}}}}, "Section colours changed"),
        ("patch", {"tweak": {"changes": {"layout": {"about": {"show": False}, "faq": {"size": "large"}}}}}, "A section hidden, heading size changed"),
        ("patch", {"tweak": {"changes": {"layout": {"about": {"show": True}}}}}, "A section shown changed"),
        ("patch", {}, "Look changed"),
    ])
    def test_labels(self, kind, checks, label):
        assert hist.change_label({"kind": kind, "checks": checks}) == label


class TestHistory:
    def test_newest_first_current_marked_and_staged_and_failed_left_out(self):
        db = premium_db()
        _row(db, id="d2", version=2, kind="patch", checks={"tweak": {"changes": {"accent": "#C0243B"}}})
        _row(db, id="d3", version=3, kind="redesign", staged=True)
        _row(db, id="d4", version=4, kind="patch", status="failed")
        db.tables["sites"][0]["current_design_id"] = "d2"
        out = hist.history(db, ORG, site(db))
        assert [h["id"] for h in out] == ["d2", "d1"]
        assert out[0]["is_current"] and not out[0]["can_restore"] and out[1]["can_restore"] and out[0]["label"] == "Brand colour changed"

    def test_only_the_last_ten_are_shown(self):
        db = premium_db()
        for i in range(2, 16):
            _row(db, id=f"d{i}", version=i, kind="patch")
        assert len(hist.history(db, ORG, site(db))) == hist.HISTORY_SHOWN


class TestRestore:
    def test_restore_moves_the_pointer_and_costs_nothing(self):
        db = premium_db()
        _row(db, id="d2", version=2, kind="patch")
        db.tables["sites"][0]["current_design_id"] = "d2"
        row = hist.restore(db, ORG, site(db), "d1")
        assert row["id"] == "d1" and site(db)["current_design_id"] == "d1"
        assert {r["id"] for r in db.rows("site_designs")} == {"d1", "d2"}          # nothing deleted: going forward again is possible

    def test_already_current_is_refused(self):
        db = premium_db()
        with pytest.raises(ValidationFailed):
            hist.restore(db, ORG, site(db), "d1")

    def test_a_held_back_or_unknown_or_foreign_version_is_not_found(self):
        db = premium_db()
        _row(db, id="d2", version=2, kind="redesign", staged=True)
        _row(db, id="d3", version=3, site_id="another-site")
        _row(db, id="d4", version=4, status="failed")
        for bad in ("d2", "d3", "d4", "nope"):
            with pytest.raises(NotFound):
                hist.restore(db, ORG, site(db), bad)

    def test_a_standard_site_has_nothing_to_restore(self):
        db = premium_db()
        db.tables["sites"][0]["tier"] = "standard"
        with pytest.raises(NotFound):
            hist.restore(db, ORG, site(db), "d1")


class TestAllowance:
    def test_default_two_included_and_none_used(self):
        s = hist.redesign_status(premium_db(), ORG, site(premium_db()))
        assert s["allowed"] and s["included"] == 2 and s["used"] == 0 and s["remaining"] == 2 and s["counts_as_edit"] is False

    def test_used_ones_come_from_events_and_block_at_the_limit(self):
        db = premium_db()
        for _ in range(2):
            db.tables["site_events"].append({"org_id": ORG, "site_id": "site-1", "event": hist.USED_EVENT})
        s = hist.redesign_status(db, ORG, site(db))
        assert not s["allowed"] and s["remaining"] == 0 and "included new designs are used" in s["blocked_reason"]

    def test_the_included_number_is_a_setting_and_zero_is_valid(self):
        assert hist.redesign_status(premium_db(site_premium_redesigns_included=5), ORG, site(premium_db()))["included"] == 5
        db = premium_db(site_premium_redesigns_included=0)
        assert not hist.redesign_status(db, ORG, site(db))["allowed"]

    def test_after_go_live_it_is_a_paid_add_on_unless_switched_on(self):
        db = premium_db()
        db.tables["sites"][0]["status"] = "live"
        s = hist.redesign_status(db, ORG, site(db))
        assert not s["allowed"] and "paid add-on" in s["blocked_reason"]
        db2 = premium_db(site_premium_post_live_redesign=True)
        db2.tables["sites"][0]["status"] = "live"
        assert hist.redesign_status(db2, ORG, site(db2))["allowed"]

    def test_progress_staged_and_a_recent_failure_are_reported(self):
        db = premium_db()
        _row(db, id="d2", version=2, kind="redesign", status="generating")
        assert hist.redesign_status(db, ORG, site(db))["in_progress"]["id"] == "d2"
        db = premium_db()
        _row(db, id="d2", version=2, kind="redesign", staged=True)
        assert hist.redesign_status(db, ORG, site(db))["staged"]["id"] == "d2"
        db = premium_db()
        _row(db, id="d2", version=2, kind="redesign", status="failed", checks={"errors": ["Out of credit"]})
        assert hist.redesign_status(db, ORG, site(db))["last_failure"] == "Out of credit"
        db = premium_db()
        _row(db, id="d2", version=2, kind="redesign", status="failed", checks={"errors": ["old"]},
             created_at=(NOW - timedelta(hours=5)).isoformat())
        assert hist.redesign_status(db, ORG, site(db))["last_failure"] is None


class TestStart:
    def test_starts_a_redesign_row_that_points_at_the_current_design(self):
        db = premium_db()
        row = hist.start_redesign(db, ORG, site(db), "builder:b1")
        saved = [r for r in db.rows("site_designs") if r["id"] == row["id"]][0]
        assert saved["kind"] == "redesign" and saved["status"] == "generating" and saved["parent_id"] == "d1"

    def test_only_premium_sites_can_try_another_design(self):
        db = _db()
        with pytest.raises(ValidationFailed):
            hist.start_redesign(db, ORG, site(db), "b")

    def test_a_waiting_design_must_be_dealt_with_first(self):
        db = premium_db()
        _row(db, id="d2", version=2, kind="redesign", staged=True)
        with pytest.raises(Conflict):
            hist.start_redesign(db, ORG, site(db), "b")

    def test_out_of_allowance_is_refused_with_402(self):
        db = premium_db(site_premium_redesigns_included=0)
        with pytest.raises(hist.RedesignNotAllowed) as e:
            hist.start_redesign(db, ORG, site(db), "b")
        assert e.value.status_code == 402 and e.value.code == "REDESIGN_NOT_INCLUDED"

    def test_the_daily_cap_still_applies(self):
        db = premium_db(site_premium_daily_per_builder=1)
        _row(db, id="d2", version=2, kind="redesign", status="ready", cost_usd=0.05)
        with pytest.raises(gen.CapReached):
            hist.start_redesign(db, ORG, site(db), "b")


class TestGenerationOfARedesign:
    def _run(self, db, claude):
        row = hist.start_redesign(db, ORG, site(db), "builder:b1")
        with patch("app.routers.sites._render_and_store") as render:
            out = gen.run_generation(db, row["id"], claude=claude)
        return row, out, render

    def test_success_is_held_back_and_counted_and_the_live_site_is_untouched(self):
        db = premium_db()
        row, out, render = self._run(db, ScriptedClaude(good_art_reply(), good_build_reply()))
        saved = [r for r in db.rows("site_designs") if r["id"] == row["id"]][0]
        assert out["ok"] and out["outcome"] == "premium_staged"
        assert saved["status"] == "ready" and saved["staged"] is True and saved["skeleton_html"]
        assert site(db)["current_design_id"] == "d1"
        render.assert_not_called()
        assert [e["event"] for e in db.rows("site_events")].count(hist.USED_EVENT) == 1
        assert hist.redesign_status(db, ORG, site(db))["used"] == 1

    def test_a_failed_redesign_is_not_counted(self):
        db = premium_db()
        _, out, _ = self._run(db, ScriptedClaude("nope", "nope"))
        assert not out["ok"] and hist.redesign_status(db, ORG, site(db))["used"] == 0
        assert site(db)["current_design_id"] == "d1"

    def test_the_current_look_is_on_the_do_not_repeat_list_first(self):
        db = premium_db()
        row = hist.start_redesign(db, ORG, site(db), "b")
        design = [r for r in db.rows("site_designs") if r["id"] == row["id"]][0]
        first = gen._do_not_repeat(db, ORG, site(db), design)[0]
        assert first.get("accent_family") == "blue"

    def test_a_first_generation_does_not_add_the_current_design(self):
        db = _db()
        row = gen.start_generation(db, ORG, site(db), "u")
        design = [r for r in db.rows("site_designs") if r["id"] == row["id"]][0]
        assert gen._do_not_repeat(db, ORG, site(db), design) == gen.recent_fingerprints(db, ORG, "p1")


class TestKeepAndDiscard:
    def staged_db(self):
        db = premium_db()
        _row(db, id="d2", version=2, kind="redesign", staged=True)
        return db

    def test_keep_makes_it_live_and_keeps_the_old_design_in_the_history(self):
        db = self.staged_db()
        hist.keep_redesign(db, ORG, site(db))
        assert site(db)["current_design_id"] == "d2"
        d2 = [r for r in db.rows("site_designs") if r["id"] == "d2"][0]
        assert d2["staged"] is False
        out = hist.history(db, ORG, site(db))
        assert [h["id"] for h in out] == ["d2", "d1"] and out[1]["can_restore"]

    def test_discard_removes_it_but_it_stays_counted(self):
        db = self.staged_db()
        db.tables["site_events"].append({"org_id": ORG, "site_id": "site-1", "event": hist.USED_EVENT})
        hist.discard_redesign(db, ORG, site(db))
        assert "d2" not in {r["id"] for r in db.rows("site_designs")} and site(db)["current_design_id"] == "d1"
        assert hist.redesign_status(db, ORG, site(db))["used"] == 1

    def test_nothing_waiting_is_not_found(self):
        db = premium_db()
        for fn in (hist.keep_redesign, hist.discard_redesign):
            with pytest.raises(NotFound):
                fn(db, ORG, site(db))

    def test_staff_choosing_a_held_back_design_releases_it(self):
        from app.services import site_premium_service as premium
        db = self.staged_db()
        premium.use_design(db, ORG, site(db), "d2")
        assert [r for r in db.rows("site_designs") if r["id"] == "d2"][0]["staged"] is False

    def test_a_held_back_design_can_be_previewed_but_a_listed_version_preview_refuses_it(self):
        db = self.staged_db()
        with patch("app.services.site_premium_service.preview_design", return_value="<html>x</html>") as p:
            assert hist.redesign_preview(db, ORG, site(db), {}) == "<html>x</html>"
            p.assert_called_once()
            with pytest.raises(NotFound):
                hist.version_preview(db, ORG, site(db), "d2", {})
            assert hist.version_preview(db, ORG, site(db), "d1", {}) == "<html>x</html>"
