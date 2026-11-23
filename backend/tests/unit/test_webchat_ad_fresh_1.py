"""AD-FRESH-1: an ad link opened over an older chat (from another source, no details yet) starts a new chat."""
from __future__ import annotations

import pathlib
from unittest.mock import patch

from fastapi import Response

from app.routers import public_webchat as pw
from app.services import webchat_service as wc

FE = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src"


def _cfg():
    return {**wc.DEFAULT_CONFIG, "campaigns": wc.clean_campaigns([{"tag": "elite-cool-sales", "main": "shop"}])}


def test_known_ad_tag_over_a_chat_from_elsewhere_without_details_restarts():
    assert wc.wants_fresh_chat(_cfg(), {"source": "catalog", "lead_id": None}, "elite-cool-sales") is True
    assert wc.wants_fresh_chat(_cfg(), {"source": "link", "lead_id": None}, "Elite-Cool-Sales") is True


def test_a_chat_with_details_also_gets_the_ad_screen():
    assert wc.wants_fresh_chat(_cfg(), {"source": "catalog", "lead_id": "lead-1"}, "elite-cool-sales") is True


def test_a_chat_a_person_is_handling_or_an_order_waiting_is_left_alone():
    assert wc.wants_fresh_chat(_cfg(), {"source": "catalog", "lead_id": "l", "state": {"pending_order": {"status": "awaiting_stock"}}}, "elite-cool-sales") is False
    assert wc.wants_fresh_chat(_cfg(), {"source": "catalog", "lead_id": "l", "state": {"pending_order": {"status": "paid"}}}, "elite-cool-sales") is True
    with patch.object(wc, "is_human", return_value=True):
        assert wc.wants_fresh_chat(_cfg(), {"source": "catalog", "lead_id": "l"}, "elite-cool-sales") is False


def test_new_chat_keeps_the_visitors_details_and_the_old_chat_is_untouched():
    from tests.unit.test_webchat_3b import ORG, _shop_db
    db = _shop_db()
    old = {"id": "old-1", "org_id": ORG, "lead_id": "lead-1", "contact_name": "Jake", "contact_phone": "+2348000000721", "phone_verified": False,
           "contact_email": "j@x.com", "consent_at": "2026-11-23T19:00:00+00:00", "consent_version": "v1", "source": "catalog", "ip_hash": "h"}
    new, token = wc.carry_session(db, old, "elite-cool-sales")
    assert token and new["source"] == "elite-cool-sales" and new["lead_id"] == "lead-1"
    assert new["contact_name"] == "Jake" and new["contact_phone"] == "+2348000000721"
    assert new.get("contact_email") == "j@x.com" and new.get("consent_version") == "v1"
    assert old["source"] == "catalog"


def test_same_tag_no_tag_and_unknown_tags_change_nothing():
    c = _cfg()
    assert wc.wants_fresh_chat(c, {"source": "elite-cool-sales", "lead_id": None}, "elite-cool-sales") is False
    assert wc.wants_fresh_chat(c, {"source": "catalog", "lead_id": None}, None) is False
    assert wc.wants_fresh_chat(c, {"source": "catalog", "lead_id": None}, "") is False
    assert wc.wants_fresh_chat(c, {"source": "catalog", "lead_id": None}, "instagram") is False
    assert wc.wants_fresh_chat(c, {"source": "catalog", "lead_id": None}, "made-up-tag") is False


def test_resume_route_restarts_carries_details_or_resumes():
    found = {"org_id": "o1", "config": _cfg()}
    anon = {"id": "s1", "source": "catalog", "lead_id": None, "org_id": "o1"}
    known = {"id": "s2", "source": "catalog", "lead_id": "lead-1", "org_id": "o1", "contact_name": "Jake"}
    newsess = {"id": "s3", "org_id": "o1", "source": "elite-cool-sales", "lead_id": "lead-1"}
    with patch.object(pw, "_chat", return_value=found), patch.object(pw, "_embed_guard"), patch.object(pw, "_snapshot", side_effect=lambda s, c, m, ad=None: {"sid": s["id"]}), \
         patch.object(wc, "list_messages", return_value=[]), patch.object(wc, "rate_limited", return_value=False), patch.object(wc, "log_event"), \
         patch.object(pw, "_first_messages", return_value=[]), patch.object(wc, "carry_session", return_value=(newsess, "tok-new")):
        with patch.object(pw, "_session", return_value=anon):
            assert pw.resume_session("k", Response(), "Bearer t", None, "elite-cool-sales", None).data == {"restart": True}
        with patch.object(pw, "_session", return_value=known):
            r = pw.resume_session("k", Response(), "Bearer t", None, "elite-cool-sales", None)
            assert r.data == {"sid": "s3", "token": "tok-new"}
            assert pw.resume_session("k", Response(), "Bearer t", None, None, None).data == {"sid": "s2"}


def test_frontend_wiring():
    p = (FE / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")
    assert "resumeChat(chatKey, stored, parentSite(), params.get('s') || undefined)" in p
    assert "if (snap && snap.restart) snap = await fresh()" in p
    assert "else if (snap && snap.token) { token.current = snap.token; writeStore(tokenKey, snap.token) }" in p
    s = (FE / "services" / "webchat.service.js").read_text(encoding="utf-8")
    assert "...(source ? { s: source } : {})" in s
