"""WA-AUTO-4c: weekly refresh of website / Google Doc sources, the "Not answered" list, and better product search."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.services import knowledge_gap_service as gaps
from app.services import knowledge_refresh_service as rf
from app.services import knowledge_service as ks
from app.services.site_import_resolve import FetchError
from tests.unit.test_wa_auto_4a import KDB, ORG, OTHER
from tests.unit.test_wa_auto_4b import Web, _site

DOC = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
DOC_URL = f"https://docs.google.com/document/d/{DOC}/edit"
EXPORT = f"https://docs.google.com/document/d/{DOC}/export?format=txt"
OLD = "Delivery is free above N50,000. Returns within 7 days."
NEW = "Delivery is free above N70,000. Returns within 14 days. We now open on Sundays."


def _db(**extra):
    return KDB(knowledge_gaps=[], products=[], **extra)


def _active_doc(db, text=OLD, **fields):
    sid = ks.new_source(db, ORG, "u1", "gdoc", "Google Doc", source_url=DOC_URL, status="processing")
    ks.fill_source(db, ORG, sid, text, page_count=1)
    ks.activate(db, ORG, sid)
    src = db.tables["knowledge_sources"][-1]
    src.update(fields)
    return sid, src


def _chunks(db, sid):
    return [c["content"] for c in db.tables["knowledge_chunks"] if c["source_id"] == sid]


# -- refreshing one source ----------------------------------------------------------------------------------------------
def test_filling_a_source_remembers_a_fingerprint_of_its_text():
    db = _db()
    sid, src = _active_doc(db)
    assert src["content_hash"] == ks.text_hash(ks.clean_text(OLD)) and src["last_refreshed_at"]


def test_unchanged_text_changes_nothing_but_the_check_date():
    db = _db()
    sid, src = _active_doc(db, last_refreshed_at="2020-01-01T00:00:00+00:00")
    before = _chunks(db, sid)
    assert rf.refresh_source(db, dict(src), Web({EXPORT: OLD.encode()})) == "unchanged"
    assert _chunks(db, sid) == before and src["last_refreshed_at"] > "2026"


def test_changed_text_replaces_the_parts_and_the_source_stays_in_use():
    db = _db()
    sid, src = _active_doc(db)
    assert rf.refresh_source(db, dict(src), Web({EXPORT: NEW.encode()})) == "updated"
    text = " ".join(_chunks(db, sid))
    assert "N70,000" in text and "N50,000" not in text
    assert src["status"] == "active" and src["content_hash"] == ks.text_hash(ks.clean_text(NEW)) and src["refresh_error"] is None
    assert src["chunk_count"] == len(_chunks(db, sid))


def test_a_failed_read_keeps_the_old_text_and_says_so():
    db = _db()
    sid, src = _active_doc(db)
    assert rf.refresh_source(db, dict(src), Web({})) == "failed"
    assert _chunks(db, sid) and "N50,000" in " ".join(_chunks(db, sid))
    assert src["status"] == "active" and "previous copy" in src["refresh_error"]


def test_a_doc_that_stopped_being_shared_is_a_failure():
    class Login(Web):
        def __call__(self, url, max_bytes=0):
            return b"<html>Sign in</html>", "text/html"
    db = _db()
    sid, src = _active_doc(db)
    assert rf.refresh_source(db, dict(src), Login({})) == "failed" and "shared" in src["refresh_error"]


def test_a_text_that_suddenly_shrinks_is_not_trusted():
    big = "Our full price list. " + "Item with a long description of the product. " * 100
    db = _db()
    sid, src = _active_doc(db, big)
    old = _chunks(db, sid)
    assert rf.refresh_source(db, dict(src), Web({EXPORT: b"Site is down for maintenance, come back later please."})) == "failed"
    assert _chunks(db, sid) == old and "much smaller" in src["refresh_error"]


def test_a_save_problem_in_the_middle_leaves_the_old_text_untouched():
    class Flaky(KDB):
        def table(self, name):
            q = super().table(name)
            if name == "knowledge_chunks" and getattr(self, "boom", False):
                orig = q.execute
                def execute():
                    if q.op == "insert":
                        raise RuntimeError("down")
                    return orig()
                q.execute = execute
            return q
    db = Flaky(knowledge_gaps=[], products=[])
    sid, src = _active_doc(db)
    db.boom = True
    assert rf.refresh_source(db, dict(src), Web({EXPORT: NEW.encode()})) == "failed"
    db.boom = False
    assert "N50,000" in " ".join(_chunks(db, sid)) and src["status"] == "active"


def test_a_website_source_is_read_with_the_same_crawler():
    db = _db()
    sid = ks.new_source(db, ORG, "u1", "url", "glow.example", source_url="https://glow.example/", status="processing")
    from app.services import knowledge_web_service as web
    web.run_website(db, ORG, sid, "https://glow.example/", _site())
    ks.activate(db, ORG, sid)
    src = db.tables["knowledge_sources"][0]
    changed = Web({**_site().pages, "https://glow.example/prices": b"<p>Braids cost N18,000 now. Wigs from N45,000.</p>"})
    assert rf.refresh_source(db, dict(src), changed) == "updated"
    assert "N18,000" in " ".join(_chunks(db, sid))


# -- the daily sweep ----------------------------------------------------------------------------------------------------
def test_due_means_not_checked_for_six_days():
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    assert rf.is_due({"last_refreshed_at": (now - timedelta(days=7)).isoformat()}, now)
    assert not rf.is_due({"last_refreshed_at": (now - timedelta(days=2)).isoformat()}, now)
    assert rf.is_due({}, now)


def test_sweep_reads_only_due_active_website_and_doc_sources(monkeypatch):
    from app.services import plan_gate_service
    monkeypatch.setattr(plan_gate_service, "allowed", lambda *a, **k: True)
    db = _db()
    old = "2020-01-01T00:00:00+00:00"
    due, d = _active_doc(db, last_refreshed_at=old)
    fresh, _ = _active_doc(db, last_refreshed_at=datetime.now(timezone.utc).isoformat())
    off, _ = _active_doc(db, last_refreshed_at=old, auto_refresh=False)
    typed = ks.add_text(db, ORG, "u1", "Typed", "Some typed answers that are long enough")
    ks.activate(db, ORG, typed["id"])
    draft = ks.new_source(db, ORG, "u1", "gdoc", "Draft", source_url=DOC_URL, status="draft")
    site = Web({EXPORT: NEW.encode()})
    out = rf.run_due(db, fetch=site)
    assert out["checked"] == 1 and out["updated"] == 1 and site.calls == [EXPORT]


def test_sweep_respects_the_run_limit_and_a_lapsed_plan(monkeypatch):
    from app.services import plan_gate_service
    monkeypatch.setattr(plan_gate_service, "allowed", lambda db, org, key: org == ORG)
    db = _db()
    for _ in range(3):
        _active_doc(db, last_refreshed_at="2020-01-01T00:00:00+00:00")
    other = ks.new_source(db, OTHER, "u1", "gdoc", "Other", source_url=DOC_URL, status="processing")
    ks.fill_source(db, OTHER, other, OLD)
    ks.activate(db, OTHER, other)
    [x for x in db.tables["knowledge_sources"] if x["id"] == other][0]["last_refreshed_at"] = "2019-01-01T00:00:00+00:00"   # the oldest, so it is looked at first
    out = rf.run_due(db, fetch=Web({EXPORT: NEW.encode()}), limit=3)
    assert out["checked"] == 3 and out["skipped"] == 1 and out["failed"] == 0      # 4 are due: 1 skipped (lapsed plan), 3 read, the 4th waits for tomorrow


def test_one_failing_source_does_not_stop_the_others(monkeypatch):
    from app.services import plan_gate_service
    monkeypatch.setattr(plan_gate_service, "allowed", lambda *a, **k: True)
    db = _db()
    a, _ = _active_doc(db, last_refreshed_at="2020-01-01T00:00:00+00:00")
    b, src_b = _active_doc(db, last_refreshed_at="2020-01-02T00:00:00+00:00")
    src_b["source_url"] = "https://docs.google.com/document/d/ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ/edit"
    out = rf.run_due(db, fetch=Web({EXPORT: NEW.encode()}))
    assert out["updated"] == 1 and out["failed"] == 1


def test_worker_and_schedule_are_registered():
    from app.workers.celery_app import celery_app
    assert celery_app.conf.beat_schedule["knowledge-refresh"]["task"] == "app.workers.knowledge_refresh_worker.run_knowledge_refresh"
    import app.workers.knowledge_refresh_worker as w
    assert w.run_knowledge_refresh.name == "app.workers.knowledge_refresh_worker.run_knowledge_refresh"


# -- the "Not answered" list -------------------------------------------------------------------------------------------
def test_a_question_is_saved_and_repeats_are_counted():
    db = _db()
    assert gaps.record(db, ORG, "Do you deliver to Abuja?", "lead-1")
    assert gaps.record(db, ORG, "  do you DELIVER to abuja ", "lead-2")
    rows = db.tables["knowledge_gaps"]
    assert len(rows) == 1 and rows[0]["times_asked"] == 2 and rows[0]["last_lead_id"] == "lead-2"


def test_phone_numbers_and_emails_are_hidden():
    db = _db()
    gaps.record(db, ORG, "Call me on +234 801 234 5678 or ada@mail.com about delivery to Ikeja?")
    q = db.tables["knowledge_gaps"][0]["question"]
    assert "801" not in q and "ada@" not in q and "[number]" in q and "[email]" in q


@pytest.mark.parametrize("bad", ["", "  ", "hi", None])
def test_empty_or_tiny_questions_are_ignored(bad):
    db = _db()
    assert gaps.record(db, ORG, bad) is False and db.tables["knowledge_gaps"] == []


def test_recording_never_raises():
    class Broken(KDB):
        def table(self, name):
            raise RuntimeError("down")
    assert gaps.record(Broken(), ORG, "Do you deliver to Abuja?") is False


def test_dismissed_stay_dismissed_but_answered_come_back_when_asked_again():
    db = _db()
    gaps.record(db, ORG, "Do you open on Sundays?")
    gid = db.tables["knowledge_gaps"][0]["id"]
    gaps.dismiss(db, ORG, gid)
    assert gaps.record(db, ORG, "Do you open on Sundays?") is False and gaps.list_open(db, ORG) == []
    db.tables["knowledge_gaps"][0]["status"] = "answered"
    assert gaps.record(db, ORG, "Do you open on Sundays?") is True and len(gaps.list_open(db, ORG)) == 1


def test_open_list_is_capped_per_business():
    db = _db()
    db.tables["knowledge_gaps"] = [{"id": str(i), "org_id": ORG, "question": f"q{i}", "question_key": f"q{i}", "status": "open", "times_asked": 1} for i in range(gaps.MAX_OPEN)]
    assert gaps.record(db, ORG, "A brand new question here?") is False
    assert gaps.record(db, OTHER, "A brand new question here?") is True


def test_most_asked_comes_first_and_only_this_business_is_listed():
    db = _db()
    gaps.record(db, ORG, "Where are you located exactly?")
    for _ in range(3):
        gaps.record(db, ORG, "Do you deliver to Abuja?")
    gaps.record(db, OTHER, "Somebody else question here")
    out = gaps.list_open(db, ORG)
    assert [g["question"] for g in out] == ["Do you deliver to Abuja?", "Where are you located exactly?"] and out[0]["times_asked"] == 3


def test_answering_adds_a_source_the_bot_uses_and_closes_the_question():
    db = _db()
    gaps.record(db, ORG, "Do you deliver to Abuja?")
    gid = db.tables["knowledge_gaps"][0]["id"]
    out = gaps.answer(db, ORG, "u1", gid, "Yes, 3 days by road, N4,500.")
    src = [s for s in db.tables["knowledge_sources"] if s["id"] == out["source_id"]][0]
    assert src["status"] == "active" and src["kind"] == "text"
    assert "Abuja" in " ".join(_chunks(db, src["id"])) and "N4,500" in " ".join(_chunks(db, src["id"]))
    assert db.tables["knowledge_gaps"][0]["status"] == "answered" and gaps.list_open(db, ORG) == []


def test_bad_answers_and_other_businesses_questions_are_refused():
    db = _db()
    gaps.record(db, ORG, "Do you deliver to Abuja?")
    gid = db.tables["knowledge_gaps"][0]["id"]
    for bad in ("", " ", "x", "y" * (gaps.MAX_ANSWER_CHARS + 1)):
        with pytest.raises(HTTPException) as e:
            gaps.answer(db, ORG, "u1", gid, bad)
        assert e.value.status_code == 422
    for fn in (lambda: gaps.answer(db, OTHER, "u1", gid, "Yes we do"), lambda: gaps.dismiss(db, OTHER, gid)):
        with pytest.raises(HTTPException) as e:
            fn()
        assert e.value.status_code == 404
    assert db.tables["knowledge_gaps"][0]["status"] == "open" and db.tables["knowledge_sources"] == []


def test_the_agent_records_only_unanswered_factual_questions(monkeypatch):
    from app.services import ai_agent_service as agent
    db = _db(leads=[], tasks=[], notifications=[], whatsapp_sessions=[{"id": "s1"}])
    monkeypatch.setattr(agent, "auto_assign_lead", lambda **k: None)
    agent._escalate_to_rep(db, ORG, {}, {"id": "s1"}, {"id": "lead-1"}, "unanswered_factual_question", "normal", {"question": "Do you deliver to Abuja?"})
    agent._escalate_to_rep(db, ORG, {}, {"id": "s1"}, {"id": "lead-1"}, "turn_limit_exceeded", "normal", {"question": "Something else entirely"})
    assert [g["question"] for g in db.tables["knowledge_gaps"]] == ["Do you deliver to Abuja?"]
    agent._escalate_to_rep(db, ORG, {}, {"id": "s1"}, None, "unanswered_factual_question", "normal", {"question": "No lead on this one?"})
    assert len(db.tables["knowledge_gaps"]) == 2          # recorded even when there is no lead to assign


# -- the routes -------------------------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset():
    yield
    from app.main import app
    app.dependency_overrides.clear()


def _client(db, monkeypatch, template="owner", ran=None):
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org
    from app.services import plan_gate_service
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: {"org_id": ORG, "id": "user-1", "roles": {"template": template}}
    monkeypatch.setattr(plan_gate_service, "allowed", lambda *a, **k: True)
    if ran is not None:
        monkeypatch.setattr(rf, "refresh_source", lambda db, src, *a, **k: ran.append(src["id"]))
    return TestClient(app)


def test_gap_routes_through_the_real_app(monkeypatch):
    db = _db()
    gaps.record(db, ORG, "Do you deliver to Abuja?")
    gaps.record(db, ORG, "Where are you located exactly?")
    c = _client(db, monkeypatch)
    listed = c.get("/api/v1/knowledge/gaps").json()["data"]
    assert len(listed) == 2
    r = c.post(f"/api/v1/knowledge/gaps/{listed[0]['id']}/answer", json={"answer": "Yes, we deliver nationwide."})
    assert r.status_code == 200 and r.json()["data"]["answered"] is True
    assert c.post(f"/api/v1/knowledge/gaps/{listed[1]['id']}/dismiss").status_code == 200
    assert c.get("/api/v1/knowledge/gaps").json()["data"] == []
    assert db.tables["audit_logs"][-1]["action"] == "knowledge.added"
    assert c.post("/api/v1/knowledge/gaps/nope/answer", json={"answer": "Yes we do"}).status_code == 404
    assert c.post(f"/api/v1/knowledge/gaps/{listed[0]['id']}/answer", json={"answer": ""}).status_code == 422


@pytest.mark.parametrize("template", ["sales_agent", ""])
def test_staff_cannot_see_or_change_the_list(monkeypatch, template):
    db = _db()
    gaps.record(db, ORG, "Do you deliver to Abuja?")
    c = _client(db, monkeypatch, template)
    assert c.get("/api/v1/knowledge/gaps").status_code == 403
    assert c.post(f"/api/v1/knowledge/gaps/{db.tables['knowledge_gaps'][0]['id']}/dismiss").status_code == 403
    assert c.get("/api/v1/knowledge/catalog").status_code == 403


def test_update_now_starts_a_read_and_cannot_be_spammed(monkeypatch):
    db, ran = _db(), []
    sid, src = _active_doc(db, last_refreshed_at="2020-01-01T00:00:00+00:00")
    c = _client(db, monkeypatch, ran=ran)
    assert c.post(f"/api/v1/knowledge/sources/{sid}/refresh").status_code == 200 and ran == [sid]
    r = c.post(f"/api/v1/knowledge/sources/{sid}/refresh")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TOO_SOON" and ran == [sid]


def test_update_now_only_for_active_websites_and_docs(monkeypatch):
    db, ran = _db(), []
    typed = ks.add_text(db, ORG, "u1", "Typed", "Some typed answers that are long enough")
    ks.activate(db, ORG, typed["id"])
    draft = ks.new_source(db, ORG, "u1", "gdoc", "Draft", source_url=DOC_URL, status="draft")
    c = _client(db, monkeypatch, ran=ran)
    assert c.post(f"/api/v1/knowledge/sources/{typed['id']}/refresh").status_code == 422
    assert c.post(f"/api/v1/knowledge/sources/{draft}/refresh").status_code == 409
    assert c.post("/api/v1/knowledge/sources/missing/refresh").status_code == 404 and ran == []


def test_weekly_update_can_be_turned_off_and_shows_in_the_list(monkeypatch):
    db = _db()
    sid, src = _active_doc(db)
    c = _client(db, monkeypatch)
    assert c.patch(f"/api/v1/knowledge/sources/{sid}/auto-refresh", json={"enabled": False}).status_code == 200
    item = [s for s in c.get("/api/v1/knowledge/sources").json()["data"] if s["id"] == sid][0]
    assert item["auto_refresh"] is False and "last_refreshed_at" in item and "refresh_error" in item
    assert c.patch("/api/v1/knowledge/sources/missing/auto-refresh", json={"enabled": True}).status_code == 404


def test_catalog_summary_counts_this_businesses_products(monkeypatch):
    db = _db()
    db.tables["products"] = [{"id": "1", "org_id": ORG}, {"id": "2", "org_id": ORG}, {"id": "3", "org_id": OTHER}]
    assert _client(db, monkeypatch).get("/api/v1/knowledge/catalog").json()["data"] == {"product_count": 2}


# -- finding products for a customer message ----------------------------------------------------------------------------
def test_search_words_keep_short_product_words_and_drop_chatter():
    from app.services.ai_agent_service import _catalog_words
    assert _catalog_words("Hello, how much are the wigs? I need 2 bags please") == {"wig", "bag"}
    assert _catalog_words("") == set() and _catalog_words(None) == set()


def _prod(i, title, desc="", tags=None):
    return {"id": f"p{i}", "org_id": ORG, "title": title, "price": 1000 * i, "variants": [{"id": f"v{i}", "title": "Std", "price": 1000 * i}],
            "catalog_images": [f"https://img/{i}.jpg"], "description": desc, "catalog_description": None, "tags": tags or {}}


def test_the_best_matching_products_come_first_and_keep_their_details():
    from app.services.ai_agent_service import _fetch_catalog_products
    db = _db()
    db.tables["products"] = [_prod(1, "Silk scarf"), _prod(2, "Body wave frontal wig", "Lace"), _prod(3, "Gift box", "Comes with a free wig cap"),
                             _prod(4, "Leather bag"), _prod(5, "Curly lace wig", tags={"style": ["curly"]})]
    out = _fetch_catalog_products(db, ORG, {}, "how much are your wigs?")
    assert [p["id"] for p in out[:3]] == ["p2", "p5", "p3"]       # name matches first, then the description match
    assert out[0]["variants"] == [{"id": "v2", "label": "Std", "price": 2000}] and out[0]["image_url"] == "https://img/2.jpg"


def test_tags_count_and_the_answer_is_capped_at_five():
    from app.services.ai_agent_service import _fetch_catalog_products, _MAX_CATALOG_PRODUCTS
    db = _db()
    db.tables["products"] = [_prod(i, f"Item {i}", tags={"colour": ["red"]}) for i in range(1, 12)] + [_prod(20, "Plain thing", tags={"colour": ["blue"]})]
    out = _fetch_catalog_products(db, ORG, {}, "anything blue?")
    assert out[0]["id"] == "p20" and len(out) == _MAX_CATALOG_PRODUCTS


def test_a_message_with_no_product_words_still_shows_the_start_of_the_catalogue():
    from app.services.ai_agent_service import _fetch_catalog_products
    db = _db()
    db.tables["products"] = [_prod(i, f"Item {i}") for i in range(1, 9)]
    assert [p["id"] for p in _fetch_catalog_products(db, ORG, {}, "hello, how are you?")] == ["p1", "p2", "p3", "p4", "p5"]
