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


def test_a_chat_with_contact_details_is_never_replaced():
    assert wc.wants_fresh_chat(_cfg(), {"source": "catalog", "lead_id": "lead-1"}, "elite-cool-sales") is False


def test_same_tag_no_tag_and_unknown_tags_change_nothing():
    c = _cfg()
    assert wc.wants_fresh_chat(c, {"source": "elite-cool-sales", "lead_id": None}, "elite-cool-sales") is False
    assert wc.wants_fresh_chat(c, {"source": "catalog", "lead_id": None}, None) is False
    assert wc.wants_fresh_chat(c, {"source": "catalog", "lead_id": None}, "") is False
    assert wc.wants_fresh_chat(c, {"source": "catalog", "lead_id": None}, "instagram") is False
    assert wc.wants_fresh_chat(c, {"source": "catalog", "lead_id": None}, "made-up-tag") is False


def test_resume_route_tells_the_page_to_restart_and_otherwise_resumes():
    found = {"org_id": "o1", "config": _cfg()}
    sess = {"id": "s1", "source": "catalog", "lead_id": None, "org_id": "o1"}
    with patch.object(pw, "_chat", return_value=found), patch.object(pw, "_session", return_value=sess), patch.object(pw, "_embed_guard"), \
         patch.object(pw, "_snapshot", return_value={"messages": []}), patch.object(wc, "list_messages", return_value=[]):
        r = pw.resume_session("k", Response(), "Bearer t", None, "elite-cool-sales", None)
        assert r.data == {"restart": True}
        r2 = pw.resume_session("k", Response(), "Bearer t", None, None, None)
        assert r2.data == {"messages": []}


def test_frontend_wiring():
    p = (FE / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")
    assert "resumeChat(chatKey, stored, parentSite(), params.get('s') || undefined)" in p
    assert "if (snap && snap.restart) snap = await fresh()" in p
    s = (FE / "services" / "webchat.service.js").read_text(encoding="utf-8")
    assert "...(source ? { s: source } : {})" in s
